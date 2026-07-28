"""서버 기준 시간과 상대 날짜 범위 계산."""

from __future__ import annotations

import re
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

FinancialReportPeriod = Literal["q1", "half", "q3", "annual"]

_EXPLICIT_YEAR_RE = re.compile(r"(?<!\d)(20\d{2})\s*년?")
_FINANCIAL_PERIOD_PATTERNS: tuple[tuple[FinancialReportPeriod, tuple[str, ...]], ...] = (
    ("q1", ("1분기", "일분기")),
    ("half", ("2분기", "이분기", "반기", "상반기")),
    ("q3", ("3분기", "삼분기")),
    ("annual", ("4분기", "사분기", "연간", "사업보고서", "결산")),
)
_FINANCIAL_HISTORY_TOKENS = (
    "추이",
    "좋아지고",
    "나빠지고",
    "개선",
    "악화",
    "늘었",
    "줄었",
    "증가",
    "감소",
    "작년보다",
    "전년보다",
    "전년대비",
    "비교",
)


def current_seoul_datetime() -> datetime:
    """요청 시점의 timezone-aware KST 일시."""

    return datetime.now(SEOUL_TIMEZONE)


def resolve_financial_time_context(
    question: str | None,
    *,
    reference_date: date,
    requested_year: int | None,
    requested_period: FinancialReportPeriod | None,
    requested_mode: Literal["latest", "exact", "history"],
) -> tuple[int | None, FinancialReportPeriod | None, Literal["latest", "exact", "history"]]:
    """질문의 상대 연도·보고기간을 서버 날짜 기준으로 정규화한다.

    회사명이나 질문 전문을 나열하지 않고 금융 기간 표현만 해석한다. 사용자가 연도를
    생략하고 특정 분기/반기를 말하면 현재 사업연도로 고정해, 모델이 데이터가 존재하는
    과거 연도로 조용히 대체하지 못하게 한다. 비교·추세 표현은 한 번의 history 조회로
    처리하도록 mode를 정규화한다.
    """

    if not question:
        return requested_year, requested_period, requested_mode

    compact = "".join(question.lower().split())
    explicit_year = _EXPLICIT_YEAR_RE.search(compact)
    relative_year_explicit = False
    if explicit_year:
        year = int(explicit_year.group(1))
    elif any(token in compact for token in ("올해", "금년", "이번해")):
        year = reference_date.year
        relative_year_explicit = True
    elif any(token in compact for token in ("작년", "지난해", "전년")):
        year = reference_date.year - 1
        relative_year_explicit = True
    else:
        year = requested_year

    period = requested_period
    for candidate, tokens in _FINANCIAL_PERIOD_PATTERNS:
        if any(token in compact for token in tokens):
            period = candidate
            if explicit_year is None and not relative_year_explicit:
                year = reference_date.year
            break

    mode = requested_mode
    if any(token in compact for token in _FINANCIAL_HISTORY_TOKENS):
        mode = "history"
    elif year is not None or period is not None:
        mode = "exact"

    return year, period, mode


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


_PRICE_CONTEXT_TOKENS = (
    "주가",
    "현재가",
    "전일대비",
    "가격",
    "시세",
    "stockprice",
)
_PRICE_MOVEMENT_TOKENS = (
    "왜",
    "이유",
    "원인",
    "배경",
    "내렸",
    "내려",
    "빠졌",
    "하락",
    "올랐",
    "올라",
    "상승",
    "급등",
    "급락",
    "움직",
)
_PRICE_REASON_TOKENS = ("왜", "이유", "원인", "배경", "호재", "악재", "영향")
_EVENT_REFERENCE_TOKENS = ("뉴스", "기사", "소식", "발표", "공시", "사건", "이슈")
_EVENT_TEMPORAL_TOKENS = ("이후", "전후", "발표후", "공시후", "나온뒤", "뜨고", "뒤주가")


def is_price_movement_question(question: str | None) -> bool:
    """실제 주가 움직임과 그 배경을 함께 묻는 질문인지 판정한다.

    회사명이나 특정 문장을 열거하지 않고 가격 문맥과 움직임/원인 문맥의 조합만 본다.
    따라서 단순한 "악재가 있었어?"는 뉴스 질문으로, "주가가 왜 내렸어?"는
    가격과 뉴스가 모두 필요한 질문으로 구분된다.
    """

    compact = "".join((question or "").lower().split())
    return any(token in compact for token in _PRICE_CONTEXT_TOKENS) and any(
        token in compact for token in _PRICE_MOVEMENT_TOKENS
    )


def is_price_driver_question(question: str | None) -> bool:
    """실제 가격 움직임의 원인·배경까지 요구한 질문인지 판정한다."""

    compact = "".join((question or "").lower().split())
    return any(token in compact for token in _PRICE_CONTEXT_TOKENS) and any(
        token in compact for token in _PRICE_REASON_TOKENS
    )


def is_event_return_question(question: str | None) -> bool:
    """특정 뉴스·공시 발표 전후의 가격 변화를 묻는 질문인지 판정한다."""

    compact = "".join((question or "").lower().split())
    return (
        any(token in compact for token in _PRICE_CONTEXT_TOKENS)
        and any(token in compact for token in _EVENT_REFERENCE_TOKENS)
        and any(token in compact for token in _EVENT_TEMPORAL_TOKENS)
    )


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
