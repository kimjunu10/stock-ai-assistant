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
    "last_month",
]


def current_seoul_datetime() -> datetime:
    """요청 시점의 timezone-aware KST 일시."""

    return datetime.now(SEOUL_TIMEZONE)


def explicit_relative_period(question: str | None) -> RelativePeriod | None:
    """사용자가 질문에 직접 표현한 상대 기간만 반환한다.

    특정 사건·인물·제품을 묻는다는 이유만으로 최근 범위를 추론하지 않는다.
    긴 표현을 먼저 검사해 ``최근``이 들어간 7일·30일 조건을 보존한다.
    """

    if not question:
        return None
    compact = "".join(question.lower().split())
    patterns: tuple[tuple[RelativePeriod, tuple[str, ...]], ...] = (
        ("last_month", ("지난달", "저번달")),
        ("this_month", ("이번달", "이달")),
        ("last_30_days", ("최근30일", "지난30일", "최근한달", "최근1개월", "지난1개월")),
        ("this_week", ("이번주", "금주")),
        ("last_7_days", ("최근7일", "지난7일", "최근일주일", "지난일주일", "1주일")),
        ("yesterday", ("어제",)),
        ("today", ("오늘",)),
        ("recent", ("최근", "요즘", "최신")),
    )
    for period, tokens in patterns:
        if any(token in compact for token in tokens):
            return period
    return None


def effective_news_relative_period(
    user_question: str | None, requested: RelativePeriod | None
) -> RelativePeriod | None:
    """Agent 요청보다 사용자가 명시한 기간을 우선하는 Tool 경계 정책.

    ``user_question``이 없는 직접 Tool 호출은 기존 API 계약대로 requested를
    보존한다. 실제 Agent 요청은 질문 원문이 항상 있으므로, 기간 표현이 없으면
    Agent가 임의로 만든 relative_period를 제거한다.
    """

    if user_question is None:
        return requested
    return explicit_relative_period(user_question)


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
    elif relative_period == "last_month":
        end = reference_date.replace(day=1) - timedelta(days=1)
        start = end.replace(day=1)
    else:  # pragma: no cover - Literal 입력 검증 뒤의 방어 코드
        raise ValueError(f"지원하지 않는 상대 기간: {relative_period}")
    return start.isoformat(), end.isoformat()
