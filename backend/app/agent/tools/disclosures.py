"""공시 Tool 2종 (Phase 5.5-B, SPEC §7.4·§7.5).

- search_disclosures: 공시 목록 검색. 기본 latest_only=True(정정 전 배제).
- get_disclosure_values: 구조화 공시 금액·날짜·수량 정확 조회(자유 SQL 금지).

FactsService(get_latest_disclosures / get_structured_values) 재사용.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.agent.tools.common import (
    SourceRef,
    ToolResult,
    clamp_items,
    clamp_text,
    error,
    iso,
    no_data,
    ok,
    sanitize_exception,
)
from app.services.facts import FactsService


class SearchDisclosuresInput(BaseModel):
    stock_code: str = Field(pattern=r"^[0-9]{6}$")
    query: str = ""
    latest_only: bool = True
    only_corrections: bool = False
    limit: int = Field(default=8, ge=1, le=12)


def run_search_disclosures(facts: FactsService, inp: SearchDisclosuresInput) -> ToolResult:
    try:
        rows = facts.get_latest_disclosures(
            inp.stock_code,
            only_corrections=inp.only_corrections,
            with_text=False,
            limit=inp.limit,
        )
    except Exception as e:  # noqa: BLE001
        return error(sanitize_exception(e))
    if not rows:
        return no_data("해당 조건의 공시를 찾지 못했습니다.")
    data, sources = [], []
    for r in clamp_items(rows, inp.limit):
        data.append(
            {
                "rcept_no": r.get("rcept_no"),
                "title": r.get("title"),
                "disclosed_at": iso(r.get("disclosed_at")),
                "correction_status": r.get("correction_status"),
                "is_latest": r.get("is_latest"),
            }
        )
        sources.append(
            SourceRef(
                source_id=r.get("rcept_no", ""),
                source_type="dart_document",
                title=r.get("title"),
                published_at=iso(r.get("disclosed_at")),
                locator={"rcept_no": r.get("rcept_no")},
            )
        )
    return ok({"disclosures": data}, sources=sources)


class DisclosureValuesInput(BaseModel):
    stock_code: str = Field(pattern=r"^[0-9]{6}$")
    event_types: list[str] = Field(default_factory=list)
    limit: int = Field(default=8, ge=1, le=12)


def run_get_disclosure_values(facts: FactsService, inp: DisclosureValuesInput) -> ToolResult:
    try:
        rows = facts.get_structured_values(
            inp.stock_code,
            event_types=inp.event_types or None,
            limit=inp.limit,
        )
    except Exception as e:  # noqa: BLE001
        return error(sanitize_exception(e))
    if not rows:
        return no_data("해당 조건의 구조화 공시 값을 찾지 못했습니다.")
    data, sources = [], []
    for r in clamp_items(rows, inp.limit):
        data.append(
            {
                "rcept_no": r.get("rcept_no"),
                "event_type": r.get("event_type"),
                "announced_at": iso(r.get("announced_at")),
                "summary": clamp_text(r.get("summary_text")),
                "normalized_data": r.get("normalized_data"),
            }
        )
        sources.append(
            SourceRef(
                source_id=r.get("rcept_no") or f"struct:{r.get('event_type')}",
                source_type="structured_disclosure",
                title=r.get("event_type"),
                published_at=iso(r.get("announced_at")),
                locator={"rcept_no": r.get("rcept_no"), "event_type": r.get("event_type")},
            )
        )
    return ok({"values": data}, sources=sources)
