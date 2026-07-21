"""DART 공시 원문에서 공식 기업 일정을 결정론적으로 추출."""

from __future__ import annotations

import re
from datetime import date, time
from typing import Any

from app.sources.dart_parsing import parse_amount

EVENT_TITLE_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("shareholders_meeting", ("주주총회소집결의", "주주총회소집공고", "정기주주총회결과")),
    ("dividend", ("현금ㆍ현물배당", "현금·현물배당")),
    ("ir", ("기업설명회(IR)",)),
    ("earnings", ("잠정)실적", "잠정실적")),
    ("record_date", ("기준일",)),
    ("book_closure", ("주주명부폐쇄",)),
)

_DATE_TEXT = r"(\d{4})\s*[.년/-]\s*(\d{1,2})\s*[.월/-]\s*(\d{1,2})\s*일?"
_TIME_TEXT = r"(\d{1,2})\s*[:시]\s*(\d{1,2})?\s*분?"


def classify_event_type(title: str) -> str | None:
    compact = re.sub(r"\s+", "", title)
    for event_type, patterns in EVENT_TITLE_PATTERNS:
        if any(re.sub(r"\s+", "", pattern) in compact for pattern in patterns):
            return event_type
    return None


def build_event_row(disclosure: dict[str, Any]) -> dict[str, Any] | None:
    title = str(disclosure.get("title") or "")
    event_type = classify_event_type(title)
    if not event_type:
        return None
    raw_text = str(disclosure.get("raw_text") or "")
    event_date = _event_date(event_type, raw_text)
    event_end_date = _find_date(raw_text, ("종료일", "폐쇄기간 종료", "종료 예정일"))
    start_time = _find_time(raw_text, ("개최시간", "개최 시각", "일시", "시간"))
    location = _find_value(raw_text, ("개최장소", "개최 장소", "장소"))
    amount = _dividend_amount(raw_text) if event_type == "dividend" else None
    status = _status(title, raw_text)
    normalized = {
        key: value
        for key, value in {
            "event_date": event_date.isoformat() if event_date else None,
            "event_end_date": event_end_date.isoformat() if event_end_date else None,
            "start_time": start_time.isoformat() if start_time else None,
            "location": location,
            "amount": amount,
        }.items()
        if value is not None
    }
    return {
        "stock_code": disclosure["stock_code"],
        "event_type": event_type,
        "title": title,
        "announced_at": disclosure.get("disclosed_at"),
        "event_date": event_date.isoformat() if event_date else None,
        "event_end_date": event_end_date.isoformat() if event_end_date else None,
        "start_time": start_time.isoformat() if start_time else None,
        "end_time": None,
        "location": location,
        "amount": amount,
        "status": status,
        "rcept_no": disclosure["rcept_no"],
        "supersedes_rcept_no": disclosure.get("supersedes_rcept_no"),
        "source_url": disclosure.get("viewer_url"),
        "normalized_data": normalized,
        "raw_text": raw_text,
        "parse_status": "success",
        "parse_error": None,
    }


def _event_date(event_type: str, text: str) -> date | None:
    labels = {
        "shareholders_meeting": ("주주총회 예정일", "주주총회일", "개최일시", "일시"),
        "dividend": ("배당기준일", "배당금지급 예정일자", "지급예정일"),
        "ir": ("개최일시", "개최 일시", "일시"),
        "earnings": ("실적공시 예정일", "발표예정일", "예정일"),
        "record_date": ("기준일",),
        "book_closure": ("폐쇄기간 시작", "시작일", "기준일"),
    }
    return _find_date(text, labels.get(event_type, ()))


def _find_date(text: str, labels: tuple[str, ...]) -> date | None:
    for label in labels:
        match = re.search(re.escape(label) + r".{0,120}?" + _DATE_TEXT, text, re.DOTALL)
        if not match:
            continue
        try:
            return date(*(int(value) for value in match.groups()))
        except ValueError:
            continue
    return None


def _find_time(text: str, labels: tuple[str, ...]) -> time | None:
    for label in labels:
        match = re.search(re.escape(label) + r".{0,160}?" + _TIME_TEXT, text, re.DOTALL)
        if not match:
            continue
        try:
            return time(int(match.group(1)), int(match.group(2) or 0))
        except ValueError:
            continue
    return None


def _find_value(text: str, labels: tuple[str, ...]) -> str | None:
    for label in labels:
        match = re.search(re.escape(label) + r"\s*[:：]?\s*([^\n]{2,240})", text)
        if match:
            value = re.sub(r"\s+", " ", match.group(1)).strip(" :-")
            return value or None
    return None


def _dividend_amount(text: str) -> int | None:
    match = re.search(r"(?:1주당|주당)\s*(?:현금)?배당금.{0,80}?(-?[\d,]+)\s*원", text, re.DOTALL)
    return parse_amount(match.group(1)) if match else None


def _status(title: str, text: str) -> str:
    head = f"{title} {text[:5000]}"
    if "철회" in head:
        return "cancelled"
    if "취소" in head:
        return "cancelled"
    if title.startswith("["):
        return "changed"
    return "scheduled"
