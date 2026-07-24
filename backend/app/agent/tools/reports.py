"""search_research_reports Tool (Phase 5.5-B, SPEC §7.6).

증권사 리포트를 기존 ResearchReportSearch 로 검색한다. active/current 청크만·partial 제외는
검색 계층(RPC + 방어)이 보장한다. 전망값을 실제 실적으로 표현하지 않도록 value_kind 를 노출한다.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.agent.tools.common import (
    SourceRef,
    ToolResult,
    clamp_items,
    clamp_text,
    error,
    no_data,
    ok,
    sanitize_exception,
)
from app.services.research_reports import ResearchReportSearch


class SearchResearchReportsInput(BaseModel):
    stock_code: str = Field(pattern=r"^[0-9]{6}$")
    query: str
    broker: str | None = None
    date_from: str | None = None
    date_to: str | None = None
    limit: int = Field(default=8, ge=1, le=12)


def run_search_research_reports(
    svc: ResearchReportSearch, inp: SearchResearchReportsInput
) -> ToolResult:
    try:
        hits = svc.search(
            inp.query,
            stock_code=inp.stock_code,
            broker=inp.broker,
            date_from=inp.date_from,
            date_to=inp.date_to,
            top_k=inp.limit,
        )
    except Exception as e:  # noqa: BLE001
        return error(sanitize_exception(e))
    if not hits:
        return no_data("해당 조건의 증권사 리포트를 찾지 못했습니다.")

    data, sources = [], []
    for h in clamp_items(hits, inp.limit):
        page = h.source_page if h.source_page is not None else h.pdf_page
        data.append(
            {
                "title": h.title,
                "broker": h.broker,
                "report_date": h.report_date,
                "investment_opinion": h.investment_opinion,
                "snippet": clamp_text(h.content),
                "page": page,
                "table_value_kinds": h.table_value_kinds,
            }
        )
        sources.append(
            SourceRef(
                source_id=h.chunk_id,
                source_type="research_report",
                title=h.title,
                publisher=h.broker,
                published_at=h.report_date,
                page=page,
                locator={
                    "report_id": h.report_id,
                    "page_number": h.page_number,
                    "pdf_page": h.pdf_page,
                    "source_page": h.source_page,
                },
            )
        )
    return ok(
        {"reports": data},
        sources=sources,
        warnings=["증권사 목표주가·전망은 예측치이며 확정 실적이 아님."],
    )
