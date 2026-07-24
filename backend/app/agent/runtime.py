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
    """6개 read-only Tool 을 LangChain @tool 로 반환. 실제 조회는 기존 Service 재사용."""

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
    ) -> str:
        """증권사 리포트를 검색한다(목표주가·투자의견·전망). 전망값은 예측치다."""
        svc, err = _services(runtime)
        if err:
            return _dump(err)
        inp = SearchResearchReportsInput(
            stock_code=stock_code,
            query=query,
            broker=broker,
            date_from=date_from,
            date_to=date_to,
        )
        return _dump(run_search_research_reports(svc.reports, inp))

    return [
        get_financial_facts,
        lookup_financial_term,
        search_news,
        search_disclosures,
        get_disclosure_values,
        search_research_reports,
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
