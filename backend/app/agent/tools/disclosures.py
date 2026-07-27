"""공시 Tool 2종 (Phase 5.5-B, SPEC §7.4·§7.5).

- search_disclosures: 공시 목록 검색. 기본 latest_only=True(정정 전 배제).
- get_disclosure_values: 구조화 공시 금액·날짜·수량 정확 조회(자유 SQL 금지).

FactsService(get_latest_disclosures / get_structured_values) 재사용.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.agent.tools.common import (
    SourceRef,
    ToolResult,
    clamp_items,
    clamp_text,
    error,
    iso,
    log_tool_exception,
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
    limit: int = Field(default=5, ge=1, le=12)


def run_search_disclosures(facts: FactsService, inp: SearchDisclosuresInput) -> ToolResult:
    try:
        rows = facts.get_latest_disclosures(
            inp.stock_code,
            only_corrections=inp.only_corrections,
            with_text=False,
            limit=inp.limit,
        )
    except Exception as e:  # noqa: BLE001
        log_tool_exception(e, layer="FactsService.get_latest_disclosures")
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
        rcept_no = r.get("rcept_no")
        # DART 공식 공개 뷰어 URL(비공개 경로·signed URL 아님). 접수번호가 있을 때만.
        dart_url = f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept_no}" if rcept_no else None
        sources.append(
            SourceRef(
                source_id=rcept_no or "",
                source_type="dart_document",
                stock_code=inp.stock_code,
                title=r.get("title"),
                published_at=iso(r.get("disclosed_at")),
                url=dart_url,
                locator={"rcept_no": rcept_no},
            )
        )
    return ok({"disclosures": data}, sources=sources)


# DB(structured_disclosures.event_type)에 실제 존재하는 값만 허용한다.
# 모델이 한국어("배당")를 넣어 no_data 가 나던 운영 결함을 스키마로 막는다.
DisclosureEventType = Literal[
    "dividend_matter",
    "treasury_stock_status",
    "treasury_stock_acquisition",
    "treasury_stock_disposal",
    "stock_total_status",
    "capital_change_status",
    "paid_in_capital_increase",
    "overseas_listing",
    "overseas_listing_decision",
]

_EVENT_TYPE_GUIDE = (
    "조회할 공시 유형(영문 코드만 허용). 사용자 표현 → 코드 대응: "
    "배당·배당금·주당배당금 → dividend_matter / "
    "자기주식·자사주 보유 현황 → treasury_stock_status / "
    "자사주 매입·취득 → treasury_stock_acquisition / "
    "자사주 처분·매각 → treasury_stock_disposal / "
    "발행주식수·상장주식수·총주식수 → stock_total_status / "
    "자본금 변동·증자·감자 이력 → capital_change_status / "
    "유상증자 → paid_in_capital_increase / "
    "해외상장 → overseas_listing, 해외상장 결정 → overseas_listing_decision. "
    "비우면 해당 종목의 최신 구조화 공시를 유형 구분 없이 조회한다. "
    "한국어 값을 넣지 말 것."
)


class DisclosureValuesInput(BaseModel):
    stock_code: str = Field(pattern=r"^[0-9]{6}$")
    event_types: list[DisclosureEventType] = Field(
        default_factory=list, description=_EVENT_TYPE_GUIDE
    )
    limit: int = Field(default=5, ge=1, le=12)


def run_get_disclosure_values(facts: FactsService, inp: DisclosureValuesInput) -> ToolResult:
    try:
        rows = facts.get_structured_values(
            inp.stock_code,
            event_types=inp.event_types or None,
            limit=inp.limit,
        )
    except Exception as e:  # noqa: BLE001
        log_tool_exception(e, layer="FactsService.get_structured_values")
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
                stock_code=inp.stock_code,
                title=r.get("event_type"),
                published_at=iso(r.get("announced_at")),
                locator={"rcept_no": r.get("rcept_no"), "event_type": r.get("event_type")},
            )
        )
    return ok({"values": data}, sources=sources)
