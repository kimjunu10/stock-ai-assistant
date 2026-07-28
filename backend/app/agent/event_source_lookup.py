"""Tool 간 사건 참조(EventRef)를 서버 원문으로 재검증한다.

검색 Tool 이 반환한 source_type/source_id 는 다음 Tool 로 전달할 수 있지만, 발표일과
종목은 모델이 전달한 값을 신뢰하지 않는다. 이 모듈이 기존 read-only 서비스로 원문을
다시 조회하고 선택 종목 경계 안에서 날짜를 확정한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal

from app.agent.context import ToolServices
from app.agent.tools.common import SourceRef

EventSourceType = Literal[
    "news_event",
    "dart_document",
    "structured_disclosure",
    "research_report",
]


@dataclass(frozen=True)
class VerifiedEventRef:
    source_type: EventSourceType
    source_id: str
    stock_code: str
    event_date: str
    title: str | None
    source: SourceRef


def _day(value) -> str | None:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip()
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        try:
            return date.fromisoformat(raw[:10]).isoformat()
        except ValueError:
            return None


def resolve_verified_event_ref(
    services: ToolServices,
    *,
    stock_code: str,
    source_type: EventSourceType,
    source_id: str,
) -> VerifiedEventRef | None:
    """불투명 사건 ID를 원문 조회로 검증한다. 없는 ID·타 종목·날짜 미상은 거절한다."""

    source_id = str(source_id or "").strip()
    if not source_id:
        return None

    if source_type == "news_event":
        chunk = services.retriever.get_news_event(source_id, stock_code=stock_code)
        event_date = _day(getattr(chunk, "published_at", None)) if chunk is not None else None
        if chunk is None or getattr(chunk, "stock_code", stock_code) not in {None, stock_code}:
            return None
        if not event_date:
            return None
        locator = getattr(chunk, "source_locator", None)
        locator = locator if isinstance(locator, dict) else {}
        return VerifiedEventRef(
            source_type=source_type,
            source_id=source_id,
            stock_code=stock_code,
            event_date=event_date,
            title=getattr(chunk, "title", None),
            source=SourceRef(
                source_id=str(getattr(chunk, "chunk_id", None) or source_id),
                source_type=source_type,
                stock_code=stock_code,
                title=getattr(chunk, "title", None),
                publisher=getattr(chunk, "publisher", None),
                published_at=str(getattr(chunk, "published_at", "") or "") or None,
                url=f"/news?cluster={source_id}" if source_id.isdigit() else None,
                locator={
                    **locator,
                    "cluster_id": int(source_id) if source_id.isdigit() else source_id,
                },
            ),
        )

    if source_type in {"dart_document", "structured_disclosure"}:
        row = services.facts.get_disclosure_by_id(source_id, stock_code=stock_code)
        event_date = _day(row.get("disclosed_at")) if row else None
        if not row or not event_date:
            return None
        rcept_no = str(row.get("rcept_no") or source_id)
        return VerifiedEventRef(
            source_type=source_type,
            source_id=rcept_no,
            stock_code=stock_code,
            event_date=event_date,
            title=row.get("title"),
            source=SourceRef(
                source_id=rcept_no,
                source_type=source_type,
                stock_code=stock_code,
                title=row.get("title"),
                published_at=str(row.get("disclosed_at") or "") or None,
                url=f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept_no}",
                locator={"rcept_no": rcept_no},
            ),
        )

    hits = services.reports.get_by_report_id(source_id, stock_code=stock_code)
    hit = hits[0] if hits else None
    event_date = _day(getattr(hit, "report_date", None)) if hit is not None else None
    if hit is None or not event_date:
        return None
    page = (
        getattr(hit, "source_page", None)
        if getattr(hit, "source_page", None) is not None
        else getattr(hit, "pdf_page", None)
    )
    return VerifiedEventRef(
        source_type=source_type,
        source_id=source_id,
        stock_code=stock_code,
        event_date=event_date,
        title=getattr(hit, "title", None),
        source=SourceRef(
            source_id=str(getattr(hit, "chunk_id", None) or source_id),
            source_type=source_type,
            stock_code=stock_code,
            title=getattr(hit, "title", None),
            publisher=getattr(hit, "broker", None),
            published_at=str(getattr(hit, "report_date", "") or "") or None,
            page=page,
            locator={"report_id": source_id, "page": page},
        ),
    )
