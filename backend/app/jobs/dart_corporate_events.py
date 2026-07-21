"""수집된 공시 원문에서 기업 일정을 추출해 멱등 저장."""

from __future__ import annotations

from app.repositories.dart import DartRepository
from app.sources.dart_events import build_event_row, classify_event_type


def collect_corporate_events(repo: DartRepository, stock_code: str) -> dict[str, int]:
    candidates = [
        row
        for row in repo.list_event_candidate_disclosures(stock_code)
        if classify_event_type(str(row.get("title") or ""))
    ]
    rows = [event for row in candidates if (event := build_event_row(row)) is not None]
    saved = repo.upsert_corporate_events(rows)
    with_date = sum(1 for row in rows if row.get("event_date"))
    return {"candidates": len(candidates), "saved": saved, "with_event_date": with_date}
