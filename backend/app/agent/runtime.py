"""금융 QA Agent 조립 (Phase 5.5-C, SPEC §8).

5.5-B 의 Tool 계약(run_*)을 LangChain @tool 로 래핑하고 create_agent 로 단일 Agent 를 만든다.
custom StateGraph·planner·keyword router·simple/complex classifier·legacy fallback 없음.

Tool 은 ToolRuntime.context(QaRuntimeContext.services)로 기존 Service 에 접근한다.
서비스 핸들은 모델 프롬프트에 노출되지 않는다.
"""

from __future__ import annotations

import json

from langchain.agents import create_agent
from langchain.agents.middleware import (
    ModelCallLimitMiddleware,
    ModelRetryMiddleware,
    ToolCallLimitMiddleware,
    ToolErrorMiddleware,
    ToolRetryMiddleware,
)
from langchain.tools import ToolRuntime, tool
from langchain_openai import ChatOpenAI

from app.agent.context import QaRuntimeContext
from app.agent.middleware import DuplicateToolCallMiddleware, sanitize_tool_error
from app.agent.prompts import FINANCIAL_AGENT_SYSTEM_PROMPT
from app.agent.tools.common import ToolResult, error
from app.agent.tools.disclosures import (
    DisclosureValuesInput,
    SearchDisclosuresInput,
    run_get_disclosure_values,
    run_search_disclosures,
)
from app.agent.tools.financials import FinancialFactsInput, run_get_financial_facts
from app.agent.tools.news import SearchNewsInput, run_search_news
from app.agent.tools.prices import (
    CalculateEventReturnInput,
    GetStockPricesInput,
    run_calculate_event_return,
    run_get_stock_prices,
)
from app.agent.tools.reports import SearchResearchReportsInput, run_search_research_reports
from app.agent.tools.terms import FinancialTermInput, run_lookup_financial_term
from app.core.config import Settings

_RETRY_TOOLS = ["search_news", "search_disclosures", "search_research_reports"]


def _dump(result: ToolResult) -> str:
    return json.dumps(result.model_dump_agent(), ensure_ascii=False)


def _services(runtime: ToolRuntime[QaRuntimeContext]):
    ctx = runtime.context
    if ctx is None or getattr(ctx, "services", None) is None:
        return None, error("실행 컨텍스트가 없어 조회할 수 없습니다.")
    return ctx.services, None


def build_tools() -> list:
    """8개 read-only Tool 을 LangChain @tool 로 반환. 실제 조회는 기존 Service 재사용.

    Phase 6 에서 get_stock_prices·calculate_event_return(실제 주가)를 추가(6→8).
    """

    @tool
    def get_financial_facts(
        stock_code: str,
        account_name: str,
        runtime: ToolRuntime[QaRuntimeContext],
        business_year: int | None = None,
        report_period: str | None = None,
        amount_type: str | None = None,
        fs_div: str = "CFS",
    ) -> str:
        """종목의 정확한 재무 수치(매출·영업이익·순이익·자산/부채/자본·현금흐름)를 조회한다.

        report_period 는 q1/half/q3/annual, amount_type 은 quarter/cumulative/point_in_time.
        정확히 일치하는 기간·유형이 없으면 no_data 를 반환하며 다른 기간으로 대체하지 않는다.
        """
        svc, err = _services(runtime)
        if err:
            return _dump(err)
        inp = FinancialFactsInput(
            stock_code=stock_code,
            account_name=account_name,
            business_year=business_year,
            report_period=report_period,
            amount_type=amount_type,
            fs_div=fs_div,
        )
        return _dump(run_get_financial_facts(svc.facts, inp))

    @tool
    def lookup_financial_term(term: str, runtime: ToolRuntime[QaRuntimeContext]) -> str:
        """금융/경제 용어의 정의를 조회한다(한국은행 경제금융용어 등)."""
        svc, err = _services(runtime)
        if err:
            return _dump(err)
        return _dump(run_lookup_financial_term(svc.facts, FinancialTermInput(term=term)))

    @tool
    def search_news(
        stock_code: str,
        query: str,
        runtime: ToolRuntime[QaRuntimeContext],
        exclude_topics: list[str] | None = None,
        include_topics: list[str] | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> str:
        """종목 뉴스 사건을 검색한다. exclude_topics 로 제외할 주제를 지정할 수 있다."""
        svc, err = _services(runtime)
        if err:
            return _dump(err)
        inp = SearchNewsInput(
            stock_code=stock_code,
            query=query,
            exclude_topics=exclude_topics or [],
            include_topics=include_topics or [],
            date_from=date_from,
            date_to=date_to,
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
        """종목 공시 목록을 검색한다. 기본적으로 정정 최신본만 반환한다."""
        svc, err = _services(runtime)
        if err:
            return _dump(err)
        inp = SearchDisclosuresInput(
            stock_code=stock_code,
            query=query,
            latest_only=latest_only,
            only_corrections=only_corrections,
        )
        return _dump(run_search_disclosures(svc.facts, inp))

    @tool
    def get_disclosure_values(
        stock_code: str,
        runtime: ToolRuntime[QaRuntimeContext],
        event_types: list[str] | None = None,
    ) -> str:
        """공시의 정확한 구조화 값(배당·증자·자기주식 등 금액/수량/날짜)을 조회한다."""
        svc, err = _services(runtime)
        if err:
            return _dump(err)
        inp = DisclosureValuesInput(stock_code=stock_code, event_types=event_types or [])
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
    ) -> str:
        """증권사 리포트를 검색한다(목표주가·투자의견·전망). 전망값은 예측치다.

        목표주가 숫자는 결과의 target_price(target_price_status='stated')만 사용한다.
        snippet 안의 숫자를 목표주가로 인용하지 않는다.
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
            stock_code=stock_code,
            query=query,
            broker=broker,
            date_from=date_from,
            date_to=date_to,
            time_context=time_context,
            as_of_date=as_of_date,
        )
        return _dump(run_search_research_reports(svc.reports, inp))

    @tool
    def get_stock_prices(
        stock_code: str,
        runtime: ToolRuntime[QaRuntimeContext],
        lookback: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        include_daily: bool = False,
    ) -> str:
        """종목의 **실제 주가**(현재가·전일 대비 등락·일봉·기간 가격)를 조회한다.

        이것은 시장에서 거래된 실제 가격이다. 증권사가 제시한 목표주가(전망)가 아니다.
        목표주가·투자의견은 search_research_reports 를 쓴다(이 Tool 이 아님).
        - 기간 미지정: 현재가 + 전일 대비 등락률(백엔드 계산).
        - lookback("1w"|"2w"|"1m"|"3m"|"6m"|"1y"): 그 기간의 실제 수익률(백엔드 계산).
        - start_date/end_date(YYYY-MM-DD): 지정 구간 수익률. 휴장일은 거래일로 스냅된다.
        수익률·등락률은 결과에 이미 계산돼 있다. 직접 산술하지 말고 결과 값을 그대로 쓴다.
        데이터가 없으면 no_data 이며 다른 날짜·종목으로 대체하지 않는다.
        """
        svc, err = _services(runtime)
        if err:
            return _dump(err)
        if svc.prices is None:
            return _dump(error("주가 조회가 현재 구성되어 있지 않습니다."))
        inp = GetStockPricesInput(
            stock_code=stock_code,
            lookback=lookback,
            start_date=start_date,
            end_date=end_date,
            include_daily=include_daily,
        )
        return _dump(run_get_stock_prices(svc.prices, inp))

    @tool
    def calculate_event_return(
        stock_code: str,
        runtime: ToolRuntime[QaRuntimeContext],
        event_date: str | None = None,
        window: str = "5d",
        lookback: str | None = None,
    ) -> str:
        """특정일/뉴스·공시 발표 전후 또는 기간의 **실제 주가 수익률**을 백엔드가 계산해 반환한다.

        "이 뉴스 발표 전후로 주가가 얼마나 움직였어?", "최근 한 달 수익률" 같은 질문에 쓴다.
        - event_date(YYYY-MM-DD) + window("1d"|"3d"|"5d"|"10d"): 사건 전후 거래일 수익률.
          event_date 는 관련 뉴스·공시의 발표일을 넣는다(그 시점 리포트 목표주가가 아님).
        - event_date 없이 lookback: 최근 기간 수익률.
        시작가·종료가·수익률·실제 사용한 거래일이 결과에 이미 계산돼 있다. Agent 는
        가격이나 수익률을 다시 계산하지 않는다. 인과("때문에")를 단정하지 말고 시간적
        관계("이후")만 표현한다. 데이터가 부족하면 no_data 다.
        """
        svc, err = _services(runtime)
        if err:
            return _dump(err)
        if svc.prices is None:
            return _dump(error("주가 조회가 현재 구성되어 있지 않습니다."))
        inp = CalculateEventReturnInput(
            stock_code=stock_code,
            event_date=event_date,
            window=window,
            lookback=lookback,
        )
        return _dump(run_calculate_event_return(svc.prices, inp))

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
        system_prompt=FINANCIAL_AGENT_SYSTEM_PROMPT,
        context_schema=QaRuntimeContext,
        middleware=middleware,
    )
