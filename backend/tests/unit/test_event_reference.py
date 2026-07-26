"""사건 후속 질문의 사건 확정 규칙 테스트 (prompt.md §4).

직전 자연어 답변을 파싱하지 않고 구조화 문맥만으로 사건을 확정하는 계약을 고정한다:
사용자 선택 우선 → 서로 다른 사건 1개면 자동 연결 → 그 외 명확화.
"""

from __future__ import annotations

from app.agent.event_reference import (
    clarification_message,
    event_date_of,
    resolve_event,
)
from app.schemas.qa import EventContext


def _ev(event_id, *, title=None, published_at=None, selected=False, stock_code="005930"):
    return EventContext(
        event_id=event_id,
        title=title,
        published_at=published_at,
        stock_code=stock_code,
        user_selected=selected,
    )


# ── (2) 서로 다른 사건이 1개면 자동 연결 ──────────────────────────
def test_single_event_auto_resolves():
    r = resolve_event(
        [_ev("news:a", title="HBM 공급계약", published_at="2026-07-22T09:00:00+09:00")]
    )
    assert r.status == "resolved"
    assert r.event.event_id == "news:a"
    assert event_date_of(r.event).isoformat() == "2026-07-22"


def test_same_event_multiple_articles_is_one_cluster():
    """같은 종목·같은 날·같은 제목의 기사 여러 건은 사건 하나로 처리한다."""
    r = resolve_event(
        [
            _ev("news:a1", title="HBM 공급계약 체결", published_at="2026-07-22T09:00:00+09:00"),
            _ev("news:a2", title="HBM 공급계약 체결", published_at="2026-07-22T11:30:00+09:00"),
            _ev("news:a3", title="HBM 공급계약 체결", published_at="2026-07-22T14:00:00+09:00"),
        ]
    )
    assert r.status == "resolved"
    # 대표는 가장 이른 원보도.
    assert r.event.event_id == "news:a1"


# ── (3) 서로 다른 사건이 여러 개면 임의 선택 금지 ─────────────────
def test_multiple_distinct_events_are_ambiguous():
    r = resolve_event(
        [
            _ev("news:a", title="HBM 공급계약", published_at="2026-07-22T09:00:00+09:00"),
            _ev("news:b", title="美 관세 발표", published_at="2026-07-18T09:00:00+09:00"),
        ]
    )
    assert r.status == "ambiguous"
    assert r.event is None
    assert {c.event_id for c in r.candidates} == {"news:a", "news:b"}


def test_clarification_message_lists_title_and_date():
    r = resolve_event(
        [
            _ev("news:a", title="HBM 공급계약", published_at="2026-07-22T09:00:00+09:00"),
            _ev("news:b", title="美 관세 발표", published_at="2026-07-18T09:00:00+09:00"),
        ]
    )
    msg = clarification_message(r.candidates)
    assert "2026-07-22" in msg and "HBM 공급계약" in msg
    assert "2026-07-18" in msg and "美 관세 발표" in msg
    # 숫자(수익률)를 만들어내지 않는다.
    assert "%" not in msg


# ── (1) 사용자가 직접 선택한 사건 우선 ────────────────────────────
def test_user_selected_event_wins_over_ambiguity():
    r = resolve_event(
        [
            _ev("news:a", title="HBM 공급계약", published_at="2026-07-22T09:00:00+09:00"),
            _ev("news:b", title="美 관세 발표", published_at="2026-07-18T09:00:00+09:00"),
        ],
        selected_event_id="news:b",
    )
    assert r.status == "resolved"
    assert r.event.event_id == "news:b"


def test_user_selected_flag_wins():
    r = resolve_event(
        [
            _ev("news:a", title="HBM 공급계약", published_at="2026-07-22T09:00:00+09:00"),
            _ev("news:b", title="美 관세", published_at="2026-07-18T09:00:00+09:00", selected=True),
        ]
    )
    assert r.status == "resolved"
    assert r.event.event_id == "news:b"


def test_unknown_selected_id_falls_back_to_normal_rules():
    """선택 id 가 문맥에 없으면 임의 선택하지 않고 일반 규칙을 적용한다."""
    r = resolve_event(
        [
            _ev("news:a", title="A", published_at="2026-07-22T09:00:00+09:00"),
            _ev("news:b", title="B", published_at="2026-07-18T09:00:00+09:00"),
        ],
        selected_event_id="news:zzz",
    )
    assert r.status == "ambiguous"


# ── 사건 문맥 없음 ────────────────────────────────────────────────
def test_no_event_context_is_none():
    assert resolve_event([]).status == "none"
    assert resolve_event(None or []).status == "none"


def test_missing_published_at_is_not_dated():
    """발표일이 없으면 날짜를 추정하지 않는다."""
    r = resolve_event([_ev("news:a", title="제목만 있음")])
    assert r.status == "resolved"
    assert event_date_of(r.event) is None


def test_malformed_published_at_is_not_dated():
    r = resolve_event([_ev("news:a", title="x", published_at="어제")])
    assert event_date_of(r.event) is None


def test_date_only_published_at_parses():
    r = resolve_event([_ev("news:a", title="x", published_at="2026-07-22")])
    assert event_date_of(r.event).isoformat() == "2026-07-22"
