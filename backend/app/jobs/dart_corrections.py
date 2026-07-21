"""정정공시를 명시된 최초 제출일과 제목으로 원 공시에 연결한다.

접수번호를 추측하지 않는다. 정정 원문에 기재된 최초 제출일과 정규화한 공시 제목이
정확히 하나의 비정정 공시를 가리킬 때만 체인을 만든다.
"""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import date, datetime
from typing import Any

from app.repositories.dart import DartRepository

_FIRST_SUBMISSION_RE = re.compile(
    r"정정대상\s*공시서류의\s*최초제출일\s*[:：]?\s*"
    r"(\d{4})\s*(?:년|[./-])\s*(\d{1,2})\s*(?:월|[./-])\s*(\d{1,2})\s*일?"
)
_PREFIX_RE = re.compile(r"^(?:\[[^\]]+\]\s*)+")


def link_corrections(repo: DartRepository, stock_code: str) -> dict[str, int]:
    rows = repo.list_disclosures_for_corrections(stock_code)
    originals: dict[tuple[str, date], list[dict[str, Any]]] = defaultdict(list)
    corrections: list[dict[str, Any]] = []

    for row in rows:
        disclosed_date = _date(row.get("disclosed_at"))
        if _is_correction_row(row):
            corrections.append(row)
        elif disclosed_date:
            originals[(_normalize_title(row.get("title")), disclosed_date)].append(row)

    linked: dict[str, list[dict[str, Any]]] = defaultdict(list)
    unlinked = 0
    for correction in corrections:
        first_date = extract_first_submission_date(correction.get("raw_text"))
        if not first_date:
            unlinked += 1
            _mark_unlinked(repo, correction)
            continue
        matches = originals.get((_normalize_title(correction.get("title")), first_date), [])
        if len(matches) != 1:
            unlinked += 1
            _mark_unlinked(repo, correction)
            continue
        original = matches[0]
        linked[original["rcept_no"]].append(correction)

    linked_count = 0
    for original_rcept, versions in linked.items():
        original = next(row for row in rows if row["rcept_no"] == original_rcept)
        ordered = [original, *sorted(versions, key=_sort_key)]
        for index, row in enumerate(ordered):
            latest = index == len(ordered) - 1
            if index == 0:
                status = "original"
                supersedes = None
            else:
                status = _correction_status(row)
                supersedes = ordered[index - 1]["rcept_no"]
                linked_count += 1
            repo.update_disclosure_version(
                row["rcept_no"],
                {
                    "original_rcept_no": original_rcept,
                    "supersedes_rcept_no": supersedes,
                    "is_latest": latest,
                    "correction_status": status,
                },
            )

    return {"corrections": len(corrections), "linked": linked_count, "unlinked": unlinked}


def extract_first_submission_date(raw_text: Any) -> date | None:
    match = _FIRST_SUBMISSION_RE.search(str(raw_text or ""))
    if not match:
        return None
    try:
        return date(*(int(value) for value in match.groups()))
    except ValueError:
        return None


def _normalize_title(value: Any) -> str:
    title = _PREFIX_RE.sub("", str(value or "").strip())
    return re.sub(r"\s+", "", title)


def _is_correction_row(row: dict[str, Any]) -> bool:
    """DART rm 플래그 오염을 피하고 원문/제목의 명시적 정정 표식을 우선한다."""

    title = str(row.get("title") or "").strip()
    raw_text = str(row.get("raw_text") or "")
    if _PREFIX_RE.match(title) or extract_first_submission_date(raw_text):
        return True
    compact_head = re.sub(r"\s+", "", raw_text[:5000])
    if "정정신고(보고)" in compact_head or "정정신고서" in compact_head:
        return True
    # 원문이 없으면 기존 DART 목록 플래그 외에 판별 근거가 없다.
    return not raw_text and bool(row.get("is_correction"))


def _date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _sort_key(row: dict[str, Any]) -> tuple[str, str]:
    return (str(row.get("disclosed_at") or ""), str(row.get("rcept_no") or ""))


def _correction_status(row: dict[str, Any]) -> str:
    text = f"{row.get('title') or ''} {row.get('raw_text') or ''}"[:10000]
    if "철회" in text:
        return "withdrawn"
    if "취소" in text:
        return "cancelled"
    return "correction"


def _mark_unlinked(repo: DartRepository, row: dict[str, Any]) -> None:
    repo.update_disclosure_version(
        row["rcept_no"],
        {
            "original_rcept_no": None,
            "supersedes_rcept_no": None,
            "is_latest": True,
            "correction_status": _correction_status(row),
        },
    )
