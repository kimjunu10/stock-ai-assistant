"""서버 기준 시간과 상대 날짜 범위 계산."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

SEOUL_TIMEZONE_NAME = "Asia/Seoul"
SEOUL_TIMEZONE = ZoneInfo(SEOUL_TIMEZONE_NAME)
RECENT_LOOKBACK_DAYS = 2

RelativePeriod = Literal[
    "recent",
    "today",
    "yesterday",
    "last_7_days",
    "last_30_days",
    "this_week",
    "this_month",
]


def current_seoul_datetime() -> datetime:
    """요청 시점의 timezone-aware KST 일시."""

    return datetime.now(SEOUL_TIMEZONE)


def resolve_relative_date_range(
    relative_period: RelativePeriod, *, reference_date: date
) -> tuple[str, str]:
    """상대 기간을 양 끝을 포함하는 ISO 날짜 범위로 변환한다."""

    if relative_period == "recent":
        start, end = reference_date - timedelta(days=RECENT_LOOKBACK_DAYS), reference_date
    elif relative_period == "today":
        start = end = reference_date
    elif relative_period == "yesterday":
        start = end = reference_date - timedelta(days=1)
    elif relative_period == "last_7_days":
        start, end = reference_date - timedelta(days=6), reference_date
    elif relative_period == "last_30_days":
        start, end = reference_date - timedelta(days=29), reference_date
    elif relative_period == "this_week":
        start, end = reference_date - timedelta(days=reference_date.weekday()), reference_date
    elif relative_period == "this_month":
        start, end = reference_date.replace(day=1), reference_date
    else:  # pragma: no cover - Literal 입력 검증 뒤의 방어 코드
        raise ValueError(f"지원하지 않는 상대 기간: {relative_period}")
    return start.isoformat(), end.isoformat()
