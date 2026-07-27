"""search_research_reports Tool (Phase 5.5-B / prompt.md §4~6).

증권사 리포트를 기존 ResearchReportSearch 로 검색한다. active/current 청크만·partial 제외는
검색 계층(RPC + 방어)이 보장한다.

목표주가 안전(prompt.md §4):
  - 목표주가 숫자는 구조화 target_price 가 status='stated' 일 때만 tool 결과에 실린다.
  - snippet 은 전망 근거·분석 검색용이며, 그 안의 숫자를 목표주가로 쓰면 안 된다.
  - 이력표 과거값·범위 합성·타 증권사 숫자 결합 금지(값 자체를 tool 이 확정해 내려준다).
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.agent.tools.common import (
    SourceRef,
    ToolResult,
    clamp_items,
    clamp_text,
    error,
    log_tool_exception,
    no_data,
    ok,
    sanitize_exception,
)
from app.services.research_reports import TIME_CONTEXTS, ResearchReportSearch


class SearchResearchReportsInput(BaseModel):
    stock_code: str = Field(pattern=r"^[0-9]{6}$")
    query: str
    broker: str | None = None
    date_from: str | None = None
    date_to: str | None = None
    # 시간 문맥(Agent 가 질문 의미로 판단해 전달). None 이면 관련도 순 기본 검색.
    time_context: str | None = None
    as_of_date: str | None = None
    # 화면 문맥으로 특정 리포트가 이미 확정된 경우("이 리포트"). 있으면 검색 없이
    # 그 리포트만 반환한다.
    report_id: str | None = None
    limit: int = Field(default=5, ge=1, le=12)


def run_search_research_reports(
    svc: ResearchReportSearch, inp: SearchResearchReportsInput
) -> ToolResult:
    if inp.report_id:
        try:
            hits = svc.get_by_report_id(inp.report_id, stock_code=inp.stock_code)
        except Exception as e:  # noqa: BLE001
            log_tool_exception(e, layer="ResearchReportSearch.get_by_report_id")
            return error(sanitize_exception(e))
        return _hits_to_result(hits, limit=inp.limit, time_context=None)
    # promptv2 §1: Agent 가 생략하면 current 를 기본값으로 쓴다(검색 계층과 동일 규칙).
    # 키워드 분기 없이 '안전한 기본값'만 제공한다.
    time_context = inp.time_context if inp.time_context in TIME_CONTEXTS else "current"
    try:
        hits = svc.search(
            inp.query,
            stock_code=inp.stock_code,
            broker=inp.broker,
            date_from=inp.date_from,
            date_to=inp.date_to,
            top_k=inp.limit,
            time_context=time_context,
            as_of_date=inp.as_of_date,
        )
    except Exception as e:  # noqa: BLE001
        log_tool_exception(e, layer="ResearchReportSearch.search")
        return error(sanitize_exception(e))
    return _hits_to_result(
        hits,
        limit=inp.limit,
        time_context=time_context,
        stock_code=inp.stock_code,
    )


def _hits_to_result(
    hits,
    *,
    limit: int,
    time_context: str | None = None,
    stock_code: str | None = None,
) -> ToolResult:
    if not hits:
        return no_data("해당 조건의 증권사 리포트를 찾지 못했습니다.")

    data, sources = [], []
    any_stale = False
    for h in clamp_items(hits, limit):
        page = h.source_page if h.source_page is not None else h.pdf_page
        # 목표주가는 status='stated' 인 구조화 값만 노출. 그 외엔 값 대신 상태만 알린다.
        tp_stated = h.target_price_status == "stated" and h.target_price is not None
        item = {
            "title": h.title,
            "broker": h.broker,
            "report_date": h.report_date,
            "investment_opinion": h.investment_opinion,
            # snippet 은 '전망 근거' 검색용. 이 안의 숫자를 목표주가로 쓰지 말 것.
            "snippet": clamp_text(h.content),
            "page": page,
            "table_value_kinds": h.table_value_kinds,
            "target_price_status": h.target_price_status,
            "is_stale": h.is_stale,
        }
        if tp_stated:
            item["target_price"] = int(h.target_price)
            item["target_price_currency"] = h.target_price_currency or "KRW"
            item["target_price_effective_date"] = h.target_price_effective_date
            item["target_price_source_page"] = h.target_price_source_page
        any_stale = any_stale or h.is_stale
        data.append(item)
        sources.append(
            SourceRef(
                source_id=h.chunk_id,
                source_type="research_report",
                stock_code=stock_code,
                title=h.title,
                publisher=h.broker,
                published_at=h.report_date,
                page=page,
                locator={
                    "report_id": h.report_id,
                    "page_number": h.page_number,
                    "pdf_page": h.pdf_page,
                    "source_page": h.source_page,
                    "target_price_source_page": h.target_price_source_page,
                    # 내부 근거 보기(prompt.md §5 우선순위 4): 원문 URL이 없으므로 클릭 시
                    # 검증된 근거 문장·페이지·목표주가만 인라인으로 펼쳐 보여준다.
                    # 비공개 저장소 경로·signed URL 은 만들지 않는다.
                    "evidence": clamp_text(h.content),
                    "investment_opinion": h.investment_opinion,
                    "target_price": int(h.target_price) if tp_stated else None,
                },
            )
        )
    warnings = [
        "증권사 목표주가·전망은 예측치이며 확정 실적이 아님.",
        "목표주가 숫자는 target_price_status='stated' 인 target_price 값만 사용할 것. "
        "snippet 텍스트의 숫자를 목표주가로 인용하지 말 것.",
    ]
    if any_stale:
        warnings.append("일부 결과는 최근 90일을 벗어난 오래된 자료(is_stale)임.")
    return ok({"reports": data, "time_context": time_context}, sources=sources, warnings=warnings)
