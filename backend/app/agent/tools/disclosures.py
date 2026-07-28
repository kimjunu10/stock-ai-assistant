"""공시 Tool 2종 (Phase 5.5-B, SPEC §7.4·§7.5).

- search_disclosures: 공시 목록 검색. 기본 latest_only=True(정정 전 배제).
- get_disclosure_values: 구조화 공시 금액·날짜·수량 정확 조회(자유 SQL 금지).

FactsService(get_latest_disclosures / get_structured_values) 재사용.
"""

from __future__ import annotations

import unicodedata
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
    current_document_id: str | None = None
    latest_only: bool = True
    only_corrections: bool = False
    limit: int = Field(default=5, ge=1, le=12)


def run_search_disclosures(facts: FactsService, inp: SearchDisclosuresInput) -> ToolResult:
    try:
        selected = (
            facts.get_disclosure_by_id(
                inp.current_document_id,
                stock_code=inp.stock_code,
            )
            if inp.current_document_id
            else None
        )
        recent_rows = facts.get_latest_disclosures(
            inp.stock_code,
            only_corrections=inp.only_corrections,
            with_text=False,
            limit=inp.limit,
        )
        rows = ([selected] if selected else []) + [
            row for row in recent_rows if row.get("rcept_no") != inp.current_document_id
        ]
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
                "event_ref": (
                    {
                        "source_type": "dart_document",
                        "source_id": str(r.get("rcept_no")),
                        "stock_code": inp.stock_code,
                    }
                    if r.get("rcept_no")
                    else None
                ),
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

DisclosureMetric = Literal[
    "cash_dividend_per_share",
    "total_cash_dividend",
    "dividend_yield",
]


def resolve_disclosure_event_types(
    question: str | None,
    requested: list[DisclosureEventType] | None = None,
) -> list[DisclosureEventType]:
    """사용자 표현을 DB의 구조화 공시 유형으로 결정적으로 정규화한다."""

    if not question:
        return list(requested or [])
    compact = "".join(unicodedata.normalize("NFKC", question).lower().split())
    resolved: list[DisclosureEventType] = []
    if "배당" in compact:
        resolved.append("dividend_matter")
    if "자기주식" in compact or "자사주" in compact:
        if any(token in compact for token in ("처분", "매각", "팔")):
            resolved.append("treasury_stock_disposal")
        elif any(token in compact for token in ("취득", "매입", "사들")):
            resolved.append("treasury_stock_acquisition")
        else:
            resolved.append("treasury_stock_status")
    if any(token in compact for token in ("발행주식수", "상장주식수", "총주식수")):
        resolved.append("stock_total_status")
    if any(token in compact for token in ("유상증자",)):
        resolved.append("paid_in_capital_increase")
    elif any(token in compact for token in ("자본금변동", "증자", "감자")):
        resolved.append("capital_change_status")
    if "해외상장" in compact:
        resolved.append("overseas_listing_decision" if "결정" in compact else "overseas_listing")
    return list(dict.fromkeys(resolved or list(requested or [])))


def resolve_disclosure_metric(
    question: str | None, requested: DisclosureMetric | None
) -> DisclosureMetric | None:
    """배당 질문의 지표 의미를 질문 원문에서 결정해 모델의 임의 선택을 막는다."""

    if not question:
        return requested
    compact = "".join(question.lower().split())
    if "배당" not in compact:
        return requested
    if "수익률" in compact:
        return "dividend_yield"
    if any(token in compact for token in ("총액", "전체배당", "배당규모")):
        return "total_cash_dividend"
    # 일상적인 "배당 얼마 줘?"는 투자자 한 주 기준 질문으로 해석한다.
    return "cash_dividend_per_share"


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
    metric: DisclosureMetric | None = Field(
        default=None,
        description=(
            "배당 수치의 의미를 고정한다. 주당 현금배당금=cash_dividend_per_share, "
            "현금배당금 총액=total_cash_dividend, 배당수익률=dividend_yield. "
            "EPS(주당순이익)는 배당금이 아니므로 반환하지 않는다."
        ),
    )
    limit: int = Field(default=5, ge=1, le=12)


def _matches_metric(row: dict, metric: DisclosureMetric) -> bool:
    normalized = row.get("normalized_data")
    if not isinstance(normalized, dict):
        return False
    label = "".join(str(normalized.get("se") or "").lower().split())
    if metric == "cash_dividend_per_share":
        return "주당" in label and "배당" in label and "순이익" not in label
    if metric == "total_cash_dividend":
        return "현금배당금총액" in label
    return "배당수익률" in label


def _metric_value(row: dict, metric: DisclosureMetric) -> dict:
    normalized = row.get("normalized_data") if isinstance(row.get("normalized_data"), dict) else {}
    value = normalized.get("thstrm")
    unit = {
        "cash_dividend_per_share": "원",
        "total_cash_dividend": "백만원",
        "dividend_yield": "%",
    }[metric]
    return {
        "metric": metric,
        "value": value,
        "unit": unit,
        "period_end": normalized.get("stlm_dt"),
        "label": normalized.get("se"),
    }


def run_get_disclosure_values(facts: FactsService, inp: DisclosureValuesInput) -> ToolResult:
    if "dividend_matter" in inp.event_types and inp.metric is None:
        return error(
            "배당 수치는 metric을 지정해야 합니다: cash_dividend_per_share, "
            "total_cash_dividend, dividend_yield"
        )
    try:
        rows = facts.get_structured_values(
            inp.stock_code,
            event_types=inp.event_types or None,
            # 한 접수번호의 여러 지표 중 요청 metric만 고르므로 필터 전에는 넉넉히 조회한다.
            limit=20 if inp.metric else inp.limit,
        )
    except Exception as e:  # noqa: BLE001
        log_tool_exception(e, layer="FactsService.get_structured_values")
        return error(sanitize_exception(e))
    if not rows:
        return no_data("해당 조건의 구조화 공시 값을 찾지 못했습니다.")
    if inp.metric:
        rows = [row for row in rows if _matches_metric(row, inp.metric)]
        if not rows:
            return no_data(f"요청한 배당 지표({inp.metric})를 찾지 못했습니다.")
    data, sources = [], []
    for r in clamp_items(rows, inp.limit):
        metric_value = _metric_value(r, inp.metric) if inp.metric else None
        data.append(
            {
                "rcept_no": r.get("rcept_no"),
                "event_ref": (
                    {
                        "source_type": "structured_disclosure",
                        "source_id": str(r.get("rcept_no")),
                        "stock_code": inp.stock_code,
                    }
                    if r.get("rcept_no")
                    else None
                ),
                "event_type": r.get("event_type"),
                "announced_at": iso(r.get("announced_at")),
                "summary": clamp_text(r.get("summary_text")),
                "normalized_data": r.get("normalized_data"),
                "metric_value": metric_value,
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
