"""사건 후속 질문 end-to-end 안전 답변 전환 테스트 (prompt.md §6).

AgentQaService 의 검증 이후 단계를 검사한다: 사건 근거가 없는데 모델이 "그 뉴스 이후
N% 올랐다"고 쓰면, 숫자를 고치지 않고 실제 상태에 맞는 안전 답변으로 **전환**한다.
"""

from __future__ import annotations

from app.agent.event_reference import EventResolution, resolve_event
from app.schemas.qa import EventContext
from app.services.agent_qa import _safe_answer_for_unsupported_event_claim

_PERIOD_ONLY = {
    "_tool_name": "get_stock_prices",
    "status": "ok",
    "data": {
        "period": {
            "start_trading_day": "2026-06-29",
            "end_trading_day": "2026-07-29",
            "start_close": 90000.0,
            "end_close": 98000.0,
            "return_pct": 8.89,
            "lookback": "1m",
        }
    },
    "sources": [{"source_id": "price:005930:2026-07-29", "source_type": "price"}],
}

_EVENT_NO_POST = {
    "_tool_name": "calculate_event_return",
    "status": "no_data",
    "data": {
        "basis": "event",
        "event_id": "news:evt-9",
        "event_date": "2026-07-26",
        "has_post_data": False,
        "baseline_trading_day": "2026-07-24",
    },
    "sources": [],
}

_FAIL = [
    "일반 기간 수익률만 근거로 있는데 답변이 '사건 이후 수익률'처럼 표현함"
    "(사건 전후 계산 결과 없음)"
]


def _single_event():
    return resolve_event(
        [EventContext(event_id="news:a", title="A", published_at="2026-07-22T09:00:00+09:00")]
    )


def _ambiguous():
    return resolve_event(
        [
            EventContext(event_id="news:a", title="HBM 공급계약", published_at="2026-07-22"),
            EventContext(event_id="news:b", title="관세 발표", published_at="2026-07-18"),
        ]
    )


# ── 이번 결함의 핵심: 최근 1개월 수익률이 '그 뉴스 이후'로 나가지 않는다 ──
def test_period_answer_is_replaced_when_event_unspecified():
    answer, switched = _safe_answer_for_unsupported_event_claim(
        "그 뉴스 이후 주가는 8.89% 상승했습니다.",
        _FAIL,
        EventResolution(status="none"),
        [_PERIOD_ONLY],
    )
    assert switched is True
    assert "8.89" not in answer  # 잘못된 기간의 숫자가 남지 않는다
    assert "특정할 수 없어" in answer
    assert "대체하지 않았습니다" in answer


def test_ambiguous_switches_to_clarification():
    answer, switched = _safe_answer_for_unsupported_event_claim(
        "그 뉴스 이후 주가는 8.89% 상승했습니다.", _FAIL, _ambiguous(), [_PERIOD_ONLY]
    )
    assert switched is True
    assert "HBM 공급계약" in answer and "관세 발표" in answer
    assert "8.89" not in answer


def test_no_post_trading_day_switches_to_data_missing():
    answer, switched = _safe_answer_for_unsupported_event_claim(
        "이 뉴스 이후 주가가 2.5% 하락했습니다.",
        ["사건 이후 주가 주장에 사건 전후 주가 계산 근거가 없음"],
        _single_event(),
        [_EVENT_NO_POST],
    )
    assert switched is True
    assert "확정 거래일 데이터가 아직 없어 계산할 수 없습니다" in answer
    assert "2.5" not in answer


def test_valid_answer_is_untouched():
    answer, switched = _safe_answer_for_unsupported_event_claim(
        "발표 이후 1거래일 3.0% 상승했습니다.", [], _single_event(), []
    )
    assert switched is False
    assert answer == "발표 이후 1거래일 3.0% 상승했습니다."


def test_unrelated_validation_errors_do_not_switch():
    """사건과 무관한 검증 오류로는 답변을 바꾸지 않는다."""
    answer, switched = _safe_answer_for_unsupported_event_claim(
        "최근 한 달 8.89% 상승했습니다.",
        ["존재하지 않는 인용 번호: [5] (근거 출처 2개)"],
        EventResolution(status="none"),
        [_PERIOD_ONLY],
    )
    assert switched is False
