"""금융 QA Agent 조립 (Phase 5.5-C, SPEC §8).

5.5-B 의 Tool 계약(run_*)을 LangChain @tool 로 래핑하고 create_agent 로 단일 Agent 를 만든다.
custom StateGraph·planner·keyword router·simple/complex classifier·legacy fallback 없음.

Tool 은 ToolRuntime.context(QaRuntimeContext.services)로 기존 Service 에 접근한다.
서비스 핸들은 모델 프롬프트에 노출되지 않는다.
"""

from __future__ import annotations

import json
import re
from datetime import date, timedelta
from typing import Literal, get_args

from langchain.agents import create_agent
from langchain.agents.middleware import (
    ModelCallLimitMiddleware,
    ModelRetryMiddleware,
    ToolCallLimitMiddleware,
    ToolErrorMiddleware,
    ToolRetryMiddleware,
    dynamic_prompt,
)
from langchain.tools import ToolRuntime, tool
from langchain_openai import ChatOpenAI
from pydantic import ValidationError

from app.agent.context import QaRuntimeContext
from app.agent.event_source_lookup import EventSourceType, resolve_verified_event_ref
from app.agent.middleware import (
    DuplicateToolCallMiddleware,
    ToolRuntimeObservabilityMiddleware,
    sanitize_tool_error,
)
from app.agent.prompts import financial_agent_system_prompt
from app.agent.time_context import (
    RelativePeriod,
    effective_news_relative_period,
    explicit_relative_period,
    is_event_return_question,
    is_price_driver_question,
    resolve_financial_time_context,
    resolve_relative_date_range,
)
from app.agent.tools.common import ToolResult, error, no_data
from app.agent.tools.disclosures import (
    DisclosureEventType,
    DisclosureMetric,
    DisclosureValuesInput,
    SearchDisclosuresInput,
    resolve_disclosure_event_types,
    resolve_disclosure_metric,
    run_get_disclosure_values,
    run_search_disclosures,
)
from app.agent.tools.financials import FinancialFactsInput, run_get_financial_facts
from app.agent.tools.news import (
    NewsSearchPurpose,
    NewsSentiment,
    SearchNewsInput,
    run_search_news,
)
from app.agent.tools.prices import (
    CalculateEventReturnInput,
    GetStockPricesInput,
    resolve_price_lookback,
    run_calculate_event_return,
    run_get_stock_prices,
)
from app.agent.tools.reports import (
    SearchResearchReportsInput,
    resolve_report_broker,
    run_search_research_reports,
)
from app.agent.tools.terms import FinancialTermInput, run_lookup_financial_term
from app.core.config import Settings
from app.services.stock_context_safety import (
    is_selected_stock_alias,
    record_runtime_stock_violation,
)

_RETRY_TOOLS = ["search_news", "search_disclosures", "search_research_reports"]
_INCOME_ACCOUNT_NAMES = {"매출액", "영업이익", "당기순이익"}
_CURRENT_DOCUMENT_RE = re.compile(
    r"이\s*(?:뉴스|기사|리포트|보고서|자료|문서)|"
    r"무슨\s*(?:뉴스|기사|리포트|보고서)|내용|핵심|요약|설명"
)
_DOCUMENT_EXPANSION_RE = re.compile(r"관련\s*(?:뉴스|기사|자료)|다른|추가|더\s*찾|최근|목록")


def _is_current_document_question(question: str | None) -> bool:
    normalized = " ".join((question or "").split())
    return bool(
        _CURRENT_DOCUMENT_RE.search(normalized) and not _DOCUMENT_EXPANSION_RE.search(normalized)
    )


def _normalize_financial_request(
    question: str | None,
    account_name: str | None,
    account_names: list[str] | None,
    amount_type: str | None,
    fs_div: str,
) -> tuple[str | None, list[str], str | None, str]:
    """모델이 흔히 혼동하는 계정 별칭·분기값·연결/별도를 질문 원문으로 고정한다."""

    aliases = {"순이익": "당기순이익", "매출": "매출액"}
    account_name = aliases.get(account_name or "", account_name)
    normalized_accounts = [aliases.get(name, name) for name in (account_names or [])]
    compact = "".join((question or "").lower().split())
    if "별도" in compact:
        fs_div = "OFS"
    elif "단독" in compact:
        # '단독 분기'는 3개월치라는 뜻이며 별도재무제표가 아니다.
        fs_div = "CFS"
    requested_accounts = {account_name, *normalized_accounts} - {None}
    has_income = not requested_accounts or bool(requested_accounts & _INCOME_ACCOUNT_NAMES)
    if has_income and re.search(r"(?:1|2|3|4)분기|반기", compact):
        if "누적" in compact:
            amount_type = "cumulative"
        else:
            # 제품 질의 계약: 'N분기'는 해당 분기 3개월치, 누적은 명시할 때만.
            amount_type = "quarter"
    return account_name, normalized_accounts, amount_type, fs_div


def _dump(result: ToolResult) -> str:
    return json.dumps(result.model_dump_agent(), ensure_ascii=False)


def _services(runtime: ToolRuntime[QaRuntimeContext]):
    ctx = runtime.context
    if ctx is None or getattr(ctx, "services", None) is None:
        return None, error("실행 컨텍스트가 없어 조회할 수 없습니다.")
    return ctx.services, None


def _resolve_stock_code(
    stock_code: str,
    runtime: ToolRuntime[QaRuntimeContext],
    *,
    tool_name: str = "unknown",
) -> str:
    """화면 종목을 authoritative context로 쓰되 다른 종목으로 fallback하지 않는다."""

    ctx_code = getattr(runtime.context, "stock_code", None)
    if not isinstance(ctx_code, str) or not re.fullmatch(r"[0-9]{6}", ctx_code):
        return stock_code

    if isinstance(stock_code, str) and re.fullmatch(r"[0-9]{6}", stock_code):
        if stock_code == ctx_code:
            return stock_code
        record_runtime_stock_violation(
            runtime.context,
            code="STOCK_CONTEXT_MISMATCH",
            tool_name=tool_name,
            provided_stock_code=stock_code,
        )
        return ""

    if not stock_code:
        return ctx_code

    if isinstance(stock_code, str) and is_selected_stock_alias(stock_code, ctx_code):
        return ctx_code

    record_runtime_stock_violation(
        runtime.context,
        code="UNSUPPORTED_STOCK",
        tool_name=tool_name,
        provided_stock_code=stock_code,
    )
    return stock_code


def _event_blocked(message: str, candidates) -> ToolResult:
    """사건 미확정으로 계산을 거부한다. 숫자를 만들지 않고 상태만 알린다.

    error 가 아니라 no_data 로 돌려 '시스템 오류'와 '근거 부족'을 구분한다(§10).
    """
    data: dict = {"basis": "event", "event_status": "unresolved"}
    if candidates:
        data["candidates"] = [
            {
                "event_id": c.event_id,
                "title": c.title,
                "published_at": c.published_at,
            }
            for c in list(candidates)[:5]
        ]
        data["event_status"] = "ambiguous"
    return no_data(message, data=data)


@dynamic_prompt
def _runtime_prompt(request) -> str:
    """모든 모델 호출에 요청 시점의 서버 시간 기준을 주입한다."""

    ctx = request.runtime.context
    return financial_agent_system_prompt(
        current_datetime=getattr(ctx, "current_datetime", None),
        current_date=getattr(ctx, "current_date", None),
        timezone=getattr(ctx, "timezone", "Asia/Seoul"),
        stock_code=getattr(ctx, "stock_code", None),
        company_name=getattr(ctx, "company_name", None),
        event_status=getattr(ctx, "event_status", "none"),
        event_title=getattr(ctx, "event_title", None),
        event_date=getattr(ctx, "event_date", None),
        event_candidates=getattr(ctx, "event_candidates", None),
        source_type=getattr(ctx, "source_type", None),
        source_id=getattr(ctx, "source_id", None),
        primary_source=getattr(ctx, "primary_source", None),
    )


def build_tools() -> list:
    """8개 read-only Tool 을 LangChain @tool 로 반환. 실제 조회는 기존 Service 재사용.

    Phase 6 에서 get_stock_prices·calculate_event_return(실제 주가)를 추가(6→8).
    """

    @tool
    def get_financial_facts(
        stock_code: str,
        runtime: ToolRuntime[QaRuntimeContext],
        account_name: str | None = None,
        account_names: list[str] | None = None,
        business_year: int | None = None,
        report_period: str | None = None,
        amount_type: str | None = None,
        fs_div: str = "CFS",
        period_mode: Literal["latest", "exact", "history"] = "latest",
    ) -> str:
        """종목의 정확한 재무 수치(매출·영업이익·순이익·자산/부채/자본·현금흐름)를 조회한다.

        특정 지표를 물으면 account_name 을 반드시 넣는다("영업이익", "매출액" 등).
        광범위한 실적 질문만 account_name 을 생략한다(매출·영업이익·순이익을 함께 조회).
        여러 특정 항목은 account_names 로 한 번에 조회한다.

        report_period: q1 | half | q3 | annual
          - "연간", "사업보고서", "N년 실적" → annual
        amount_type: cumulative | quarter | point_in_time
          - "누적" → cumulative
          - "단독", "당기", "3개월", "분기 자체" → quarter
          - 자산·부채·자본(재무상태표) → point_in_time
          - 연간 손익 → cumulative

        fs_div: CFS(연결, 기본) | OFS(별도)
          - "별도 기준", "별도재무제표"라고 명시할 때만 OFS 를 쓴다.
          - 주의: "단독 3분기 영업이익"의 '단독'은 별도재무제표가 아니라
            누적이 아닌 3개월치라는 뜻이다 → amount_type=quarter, fs_div 는 CFS 유지.

        제품 질의 계약에서 "3분기 영업이익"은 해당 분기 3개월치(quarter)로 해석한다.
        누적값은 사용자가 "누적"을 명시한 경우에만 cumulative 로 조회한다.

        정확히 일치하는 기간·유형이 없으면 no_data 를 반환하며 다른 기간으로 대체하지 않는다.
        """
        svc, err = _services(runtime)
        if err:
            return _dump(err)
        (
            account_name,
            account_names,
            amount_type,
            fs_div,
        ) = _normalize_financial_request(
            getattr(runtime.context, "user_question", None),
            account_name,
            account_names,
            amount_type,
            fs_div,
        )
        current_date = getattr(runtime.context, "current_date", None)
        if current_date:
            business_year, report_period, period_mode = resolve_financial_time_context(
                getattr(runtime.context, "user_question", None),
                reference_date=date.fromisoformat(current_date),
                requested_year=business_year,
                requested_period=report_period,
                requested_mode=period_mode,
            )
        inp = FinancialFactsInput(
            stock_code=_resolve_stock_code(
                stock_code,
                runtime,
                tool_name="get_financial_facts",
            ),
            account_name=account_name,
            account_names=account_names,
            business_year=business_year,
            report_period=report_period,
            amount_type=amount_type,
            fs_div=fs_div,
            period_mode=period_mode,
        )
        return _dump(run_get_financial_facts(svc.facts, inp))

    @tool
    def lookup_financial_term(term: str, runtime: ToolRuntime[QaRuntimeContext]) -> str:
        """금융·경제·공시 양식 용어의 정의를 공식 출처 사전에서 조회한다."""
        svc, err = _services(runtime)
        if err:
            return _dump(err)
        return _dump(run_lookup_financial_term(svc.facts, FinancialTermInput(term=term)))

    @tool
    def search_news(
        stock_code: str,
        runtime: ToolRuntime[QaRuntimeContext],
        query: str | None = None,
        sentiment: NewsSentiment | None = None,
        exclude_topics: list[str] | None = None,
        include_topics: list[str] | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        relative_period: RelativePeriod | None = None,
        purpose: NewsSearchPurpose = "general",
    ) -> str:
        """종목 뉴스 사건을 검색한다.

        stock_code: 항상 6자리 숫자 코드(예: 005930). 제공된 문맥의 종목코드를 쓰고,
        회사명("삼성"/"삼성전자"/"하이닉스" 등)을 이 자리에 넣지 말 것.

        query(검색 주제):
        - 특정 사건·제품·주제가 있을 때만 채운다. 예: "HBM 공급계약", "배당", "화재".
          이 경우 의미 검색 + 키워드 검색으로 관련 뉴스를 찾는다.
        - 특정 주제가 없으면 query를 비운다(생략). 예: "어제 무슨 일 있었어?",
          "최근 뉴스", "어제 악재/호재 있었어?"는 주제가 아니라 기간·감성 조건이므로
          query를 넣지 말 것. 이때는 종목·기간·감성으로 최신 뉴스 사건을 조회한다.
        - query에 종목명만 억지로 넣지 말 것(그건 주제가 아니다).

        sentiment(감성): 사용자가 악재/호재/부정/긍정을 물으면 지정한다.
          positive(호재/긍정) | negative(악재/부정) | neutral. 없으면 생략.

        기간: relative_period(recent/today/yesterday/last_7_days/last_30_days/
        this_week/this_month/last_month)로 상대 기간을 지정한다. recent는 KST 오늘부터
        2일 전까지. 사용자가 기간을 직접 말한 경우에만 지정하고, 특정 사건·인물·제품을
        묻더라도 기간 표현이 없으면 반드시 생략한다.
        date_from/date_to는 사용자가 절대 날짜를 지정한 경우에만 쓴다.

        purpose: 일반 뉴스는 general. 실제 주가 하락의 관련 요인은 price_driver_down,
        상승의 관련 요인은 price_driver_up을 쓴다. 두 price_driver 목적은 제목부터 해당
        기업을 직접 식별하는 사건만 반환하며, 각각 negative/positive 감성을 강제한다.
        """
        svc, err = _services(runtime)
        if err:
            return _dump(err)
        question = getattr(runtime.context, "user_question", None)
        if (
            getattr(runtime.context, "event_status", "none") == "resolved"
            and is_event_return_question(question)
            and not is_price_driver_question(question)
        ):
            return _dump(
                no_data(
                    "사용자가 지정한 사건의 발표 전후 가격만 묻고 있어 최신 뉴스를 "
                    "추가 검색하지 않았습니다."
                )
            )
        if purpose in {"price_driver_down", "price_driver_up"} and not is_price_driver_question(
            question
        ):
            # 모델이 "오늘 악재 있어?" 같은 일반 뉴스 질문을 주가 원인 검색으로
            # 잘못 라우팅해도 조회 자체를 버리지 않는다. 방향 감성만 보존하고 일반
            # 뉴스 검색으로 낮춰 같은 질문이 매번 동일한 데이터 경로를 타게 한다.
            sentiment = "negative" if purpose == "price_driver_down" else "positive"
            purpose = "general"
        relative_period = effective_news_relative_period(
            question,
            relative_period,
        )
        if purpose == "price_driver_down":
            sentiment = "negative"
        elif purpose == "price_driver_up":
            sentiment = "positive"
        if relative_period:
            current_date = getattr(runtime.context, "current_date", None)
            if not current_date:
                return _dump(error("서버의 현재 날짜를 확인할 수 없습니다."))
            try:
                date_from, date_to = resolve_relative_date_range(
                    relative_period, reference_date=date.fromisoformat(current_date)
                )
            except ValueError:
                return _dump(error("서버의 날짜 기준이 올바르지 않습니다."))
        inp = SearchNewsInput(
            stock_code=_resolve_stock_code(
                stock_code,
                runtime,
                tool_name="search_news",
            ),
            query=query,
            sentiment=sentiment,
            exclude_topics=exclude_topics or [],
            include_topics=include_topics or [],
            date_from=date_from,
            date_to=date_to,
            current_event_id=(
                getattr(runtime.context, "source_id", None)
                if getattr(runtime.context, "source_type", None) == "news_event"
                else None
            ),
            context_only=(
                getattr(runtime.context, "source_type", None) == "news_event"
                and _is_current_document_question(getattr(runtime.context, "user_question", None))
            ),
            purpose=purpose,
        )
        return _dump(run_search_news(svc.retriever, inp))

    @tool
    def search_disclosures(
        stock_code: str,
        query: str,
        runtime: ToolRuntime[QaRuntimeContext],
        latest_only: bool = True,
        only_corrections: bool = False,
    ) -> str:
        """종목 공시 목록을 검색한다. 기본적으로 정정 최신본만 반환한다.

        stock_code: 항상 6자리 숫자 코드(예: 005930). 문맥의 종목코드를 쓰고
        회사명을 이 자리에 넣지 말 것.
        """
        svc, err = _services(runtime)
        if err:
            return _dump(err)
        question = getattr(runtime.context, "user_question", None)
        event_types = resolve_disclosure_event_types(question)
        if event_types:
            # 정확한 수량·금액 질문을 모델이 목록 검색으로 호출해도 구조화 행을 우선한다.
            return _dump(
                run_get_disclosure_values(
                    svc.facts,
                    DisclosureValuesInput(
                        stock_code=_resolve_stock_code(
                            stock_code,
                            runtime,
                            tool_name="search_disclosures",
                        ),
                        event_types=event_types,
                        metric=resolve_disclosure_metric(question, None),
                    ),
                )
            )
        inp = SearchDisclosuresInput(
            stock_code=_resolve_stock_code(
                stock_code,
                runtime,
                tool_name="search_disclosures",
            ),
            query=query,
            current_document_id=(
                getattr(runtime.context, "source_id", None)
                if getattr(runtime.context, "source_type", None)
                in {"dart_document", "structured_disclosure"}
                else None
            ),
            latest_only=latest_only,
            only_corrections=only_corrections,
        )
        return _dump(run_search_disclosures(svc.facts, inp))

    @tool
    def get_disclosure_values(
        stock_code: str,
        runtime: ToolRuntime[QaRuntimeContext],
        event_types: list[DisclosureEventType] | None = None,
        metric: DisclosureMetric | None = None,
    ) -> str:
        """공시의 정확한 구조화 값(배당·증자·자기주식 등 금액/수량/날짜)을 조회한다.

        event_types 는 영문 코드만 허용한다(한국어 금지). 사용자 표현 대응:
        배당·주당배당금 → dividend_matter, 자사주 보유 → treasury_stock_status,
        자사주 매입 → treasury_stock_acquisition, 자사주 처분 → treasury_stock_disposal,
        발행주식수·상장주식수 → stock_total_status, 자본금 변동·증자/감자 →
        capital_change_status, 유상증자 → paid_in_capital_increase,
        해외상장 → overseas_listing / overseas_listing_decision.
        배당 금액을 물으면 metric을 반드시 지정한다:
        주당 배당금=cash_dividend_per_share, 배당 총액=total_cash_dividend,
        배당수익률=dividend_yield. EPS(주당순이익)는 배당금이 아니다.
        event_types를 생략하면 최신 구조화 공시를 유형 구분 없이 조회한다.
        """
        svc, err = _services(runtime)
        if err:
            return _dump(err)
        try:
            metric = resolve_disclosure_metric(
                getattr(runtime.context, "user_question", None),
                metric,
            )
            event_types = resolve_disclosure_event_types(
                getattr(runtime.context, "user_question", None),
                event_types,
            )
            inp = DisclosureValuesInput(
                stock_code=_resolve_stock_code(
                    stock_code,
                    runtime,
                    tool_name="get_disclosure_values",
                ),
                event_types=event_types,
                metric=metric,
            )
        except ValidationError:
            # 허용되지 않은 값은 '데이터 없음'이 아니라 입력 오류로 알린다.
            # no_data 로 뭉개면 모델이 "공시가 없다"고 잘못 답한다(운영 결함).
            return _dump(
                error(
                    "event_types 에 허용되지 않은 값이 있습니다. 영문 코드만 사용하세요: "
                    + ", ".join(get_args(DisclosureEventType))
                )
            )
        return _dump(run_get_disclosure_values(svc.facts, inp))

    @tool
    def search_research_reports(
        stock_code: str,
        query: str,
        runtime: ToolRuntime[QaRuntimeContext],
        broker: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        time_context: str | None = None,
        as_of_date: str | None = None,
        report_id: str | None = None,
    ) -> str:
        """증권사 리포트를 검색한다(목표주가·투자의견·전망). 전망값은 예측치다.

        stock_code: 항상 6자리 숫자 코드(예: 005930). 문맥의 종목코드를 쓰고
        회사명을 이 자리에 넣지 말 것.
        목표주가 숫자는 결과의 target_price(target_price_status='stated')만 사용한다.
        snippet 안의 숫자를 목표주가로 인용하지 않는다.
        broker: 사용자가 특정 증권사를 지목하면("대신증권 리포트", "미래에셋에서는")
        그 증권사명을 반드시 이 인자로 넘긴다. query 에만 넣으면 다른 증권사 리포트가
        섞여 나온다. 지목이 없으면 생략한다.
        query: 검색 주제(예: "목표주가", "실적 전망"). 사용자가 최근 리포트
        "목록"만 요청하고 특정 주제가 없으면 빈 문자열로 둔다(최신순 목록 반환).
        report_id: 현재 문서 문맥(서버 확정)에 report_id 가 있고 사용자가 "이 리포트",
        "이 문서" 처럼 그 리포트를 가리키면 이 인자에 그 값을 그대로 넣는다. 검색 없이
        해당 리포트만 바로 반환한다. 이 값이 있으면 query/broker/time_context 는 무시된다.
        time_context 로 검색의 시간 기준을 준다(생략하면 "current" 가 기본):
          - "current"(기본): 최근 증권사 의견/목표주가(증권사별 최신 1건, 오래된 자료 표시).
            '지금 목표주가/전망' 질문은 이 값을 쓴다(이력·타 종목 값이 섞이지 않음).
          - "historical_point": 특정 과거 시점의 의견 — date_from/date_to 로 범위 지정
          - "around_event": 공시·실적 발표 전후 — date_from/date_to 로 사건 전후 범위
          - "history": 목표주가·투자의견 '변동 이력'(날짜별 개별값) — 변화 추이 질문에만 쓴다.
        as_of_date(YYYY-MM-DD)는 current 기준일. 미지정 시 최신 리포트 기준.
        """
        svc, err = _services(runtime)
        if err:
            return _dump(err)
        inp = SearchResearchReportsInput(
            stock_code=_resolve_stock_code(
                stock_code,
                runtime,
                tool_name="search_research_reports",
            ),
            query=query,
            broker=resolve_report_broker(
                getattr(runtime.context, "user_question", None),
                broker,
            ),
            date_from=date_from,
            date_to=date_to,
            time_context=time_context,
            as_of_date=as_of_date,
            report_id=(
                getattr(runtime.context, "source_id", None)
                if getattr(runtime.context, "source_type", None) == "research_report"
                and _is_current_document_question(getattr(runtime.context, "user_question", None))
                else report_id
            ),
        )
        return _dump(run_search_research_reports(svc.reports, inp))

    @tool
    def get_stock_prices(
        stock_code: str,
        runtime: ToolRuntime[QaRuntimeContext],
        lookback: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        target_date: str | None = None,
        include_daily: bool = False,
    ) -> str:
        """종목의 **실제 주가**(최근 가격·전일 대비 등락·일봉·기간 가격)를 조회한다.

        이것은 시장에서 거래된 실제 가격이다. 증권사가 제시한 목표주가(전망)가 아니다.
        목표주가·투자의견은 search_research_reports 를 쓴다(이 Tool 이 아님).
        - 기간 미지정: 제공자의 최근 가격 + 직전 확정 종가 대비 등락률(백엔드 계산).
        - lookback("1w"|"2w"|"1m"|"3m"|"6m"|"1y"): 그 기간의 실제 수익률(백엔드 계산).
        - start_date/end_date(YYYY-MM-DD): 지정 구간 수익률. 휴장일은 거래일로 스냅된다.
        - target_date(YYYY-MM-DD): 특정 과거 하루의 확정 등락률. 해당 거래일 종가를
          직전 거래일 종가와 비교한다.
        - 기간 비교에는 해당 구간의 실제 거래일 가격이 함께 반환되어 UI가 그 구간만
          선그래프로 그린다. 장중 마지막 점은 확정 종가가 아니라 현재가다.
        - include_daily=true는 명시적인 흐름·추이·그래프 요청을 나타내는 힌트다.
        수익률·등락률은 결과에 이미 계산돼 있다. 직접 산술하지 말고 결과 값을 그대로 쓴다.
        데이터가 없으면 no_data 이며 다른 날짜·종목으로 대체하지 않는다.
        """
        svc, err = _services(runtime)
        if err:
            return _dump(err)
        if svc.prices is None:
            return _dump(error("주가 조회가 현재 구성되어 있지 않습니다."))
        try:
            lookback = resolve_price_lookback(
                getattr(runtime.context, "user_question", None),
                lookback,
            )
        except ValueError as exc:
            return _dump(error(str(exc)))
        question = getattr(runtime.context, "user_question", None)
        if explicit_relative_period(question) == "yesterday":
            current_date = getattr(runtime.context, "current_date", None)
            if not current_date:
                return _dump(error("서버의 현재 날짜를 확인할 수 없습니다."))
            try:
                target_date = (date.fromisoformat(current_date) - timedelta(days=1)).isoformat()
            except ValueError:
                return _dump(error("서버의 날짜 기준이 올바르지 않습니다."))
            # 모델이 현재가·임의 기간 인자를 함께 보내도 사용자가 명시한 '어제'를 우선한다.
            lookback = None
            start_date = None
            end_date = None
        inp = GetStockPricesInput(
            stock_code=_resolve_stock_code(
                stock_code,
                runtime,
                tool_name="get_stock_prices",
            ),
            lookback=lookback,
            start_date=start_date,
            end_date=end_date,
            target_date=target_date,
            include_daily=include_daily,
        )
        return _dump(run_get_stock_prices(svc.prices, inp))

    @tool
    def calculate_event_return(
        stock_code: str,
        runtime: ToolRuntime[QaRuntimeContext],
        window: str = "5d",
        event_source_type: EventSourceType | None = None,
        event_source_id: str | None = None,
    ) -> str:
        """특정 뉴스·공시 **발표 전후**의 실제 주가 변화를 백엔드가 계산해 반환한다.

        "이 뉴스 이후 주가가 어떻게 됐어?", "발표 후 1·3·5거래일 주가는?" 같은 사건 기준
        질문에만 쓴다. 최근 한 달·일주일 같은 **일반 기간** 수익률은 이 Tool 이 아니라
        get_stock_prices(lookback=...)를 쓴다.

        사건 발표일은 서버가 확정한다. 현재 화면/후속 질문의 사건은 인자 없이 사용한다.
        같은 질문에서 search_news·search_disclosures·search_research_reports 로 사건을
        찾았다면, 결과의 event_ref에 있는 source_type/source_id만 그대로 넘긴다.
        발표일을 인자로 넘기거나 기억으로 추정하지 않는다. 서버는 ID로 원문을 다시
        조회해 종목과 날짜를 검증한다. 검색 결과가 여러 개인데 사용자가 특정하지 않았다면
        임의로 고르지 말고, '최근/가장 최근/첫 번째'처럼 기준이 명확할 때만 해당 1건의
        event_ref를 사용한다.

        결과는 발표 전 마지막 확정 거래일 종가 기준, 발표 후 1·3·5거래일 종가·수익률이다.
        발표 이후 확정 거래일이 없으면 no_data 이며 다른 기간으로 대체하지 않는다.
        수익률은 이미 계산돼 있다. 직접 산술하지 말고 결과 값과 거래일을 그대로 쓴다.
        인과("때문에")를 단정하지 말고 시간적 관계("이후")만 표현한다.
        """
        svc, err = _services(runtime)
        if err:
            return _dump(err)
        if svc.prices is None:
            return _dump(error("주가 조회가 현재 구성되어 있지 않습니다."))

        # 사건 날짜·종목은 코드가 원문으로 확정한다(모델 선택·추정 차단).
        ctx = runtime.context
        status = getattr(ctx, "event_status", "none")
        selected_stock_code = _resolve_stock_code(
            getattr(ctx, "event_stock_code", None) or stock_code,
            runtime,
            tool_name="calculate_event_return",
        )
        event_date = getattr(ctx, "event_date", None) if status == "resolved" else None
        event_id = getattr(ctx, "event_id", None) if event_date else None
        verified = None

        # 현재 화면의 정확한 뉴스·공시·리포트도 별도 event_context 없이 사건 기준이 된다.
        primary = getattr(ctx, "primary_source", None)
        primary_type = primary.get("source_type") if isinstance(primary, dict) else None
        primary_id = primary.get("context_source_id") if isinstance(primary, dict) else None
        if not event_date and primary_type and primary_id:
            verified = resolve_verified_event_ref(
                svc,
                stock_code=selected_stock_code,
                source_type=primary_type,
                source_id=str(primary_id),
            )

        # 같은 턴의 검색 결과 EventRef. 모델이 전달한 날짜는 받지 않고 ID로 재조회한다.
        if not event_date and verified is None and event_source_type and event_source_id:
            verified = resolve_verified_event_ref(
                svc,
                stock_code=selected_stock_code,
                source_type=event_source_type,
                source_id=event_source_id,
            )
            if verified is None:
                return _dump(
                    _event_blocked(
                        "검색 결과의 사건 참조를 원문에서 확인할 수 없어 사건 전후 주가를 "
                        "계산하지 않았습니다. 다른 사건이나 최근 기간 수익률로 대체하지 마십시오.",
                        None,
                    )
                )

        if verified is not None:
            event_date = verified.event_date
            event_id = verified.source_id

        if not event_date and status == "ambiguous":
            return _dump(
                _event_blocked(
                    "서로 다른 사건이 여러 개라 어떤 사건인지 확정할 수 없습니다. "
                    "사용자에게 사건을 되물어야 합니다. 임의로 하나를 고르거나 "
                    "최근 기간 수익률로 대체하지 마십시오.",
                    getattr(ctx, "event_candidates", None),
                )
            )
        if not event_date:
            return _dump(
                _event_blocked(
                    "사건 정보(발표일)가 문맥에 없어 사건 전후 주가를 계산할 수 없습니다. "
                    "최근 한 달·일주일 수익률로 대체하지 말고, 어떤 뉴스·공시를 말하는지 "
                    "사용자에게 확인해야 합니다.",
                    None,
                )
            )

        inp = CalculateEventReturnInput(
            stock_code=selected_stock_code,
            event_date=event_date,
            event_id=event_id,
            window=window,
        )
        result = run_calculate_event_return(svc.prices, inp)
        if verified is not None:
            result.sources.insert(0, verified.source)
            if isinstance(result.data, dict):
                result.data["event"] = {
                    "source_type": verified.source_type,
                    "source_id": verified.source_id,
                    "stock_code": verified.stock_code,
                    "title": verified.title,
                    "published_at": verified.event_date,
                }
        return _dump(result)

    return [
        get_financial_facts,
        lookup_financial_term,
        search_news,
        search_disclosures,
        get_disclosure_values,
        search_research_reports,
        get_stock_prices,
        calculate_event_return,
    ]


def build_agent(cfg: Settings, *, api_key: str, base_url: str):
    """create_agent 로 단일 금융 QA Agent 를 만든다.

    모델·Tool·시스템 프롬프트·context_schema·안전장치 middleware 를 연결한다.
    전체 timeout 은 실행 계층(agent_qa)에서 적용한다.
    """
    model = ChatOpenAI(
        model=cfg.agent_chat_model,
        api_key=api_key,
        base_url=base_url,
        temperature=0,
        # 개별 호출 HTTP timeout + 무재시도: API hang 이 전체 응답을 매달리지 않게 한다.
        timeout=cfg.agent_model_timeout_seconds,
        max_retries=0,
    )
    middleware = [
        _runtime_prompt,
        ToolRuntimeObservabilityMiddleware(),
        ModelCallLimitMiddleware(run_limit=cfg.agent_max_model_calls, exit_behavior="end"),
        ToolCallLimitMiddleware(run_limit=cfg.agent_max_tool_calls, exit_behavior="end"),
        DuplicateToolCallMiddleware(max_repeats=cfg.agent_max_same_tool_args),
        ToolRetryMiddleware(max_retries=cfg.agent_tool_retry, tools=_RETRY_TOOLS),
        ModelRetryMiddleware(max_retries=1),
        ToolErrorMiddleware(on_error=sanitize_tool_error),
    ]
    return create_agent(
        model=model,
        tools=build_tools(),
        context_schema=QaRuntimeContext,
        middleware=middleware,
    )
