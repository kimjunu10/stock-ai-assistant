"""사건 기반 주장 검증 테스트 (prompt.md §6).

"이 뉴스 이후 …% 올랐다" 류 주장은 사건 전후 계산 근거가 있어야 통과한다.
일반 기간(최근 한 달) 수익률만 있는 상태로 사건 이후처럼 표현하면 검증 실패다.
검증기는 숫자를 고치거나 보충하지 않는다 — 오류만 기록한다.
"""

from __future__ import annotations

from app.agent.validator import (
    collect_evidence,
    sanitize_causal_language,
    sanitize_price_movement_claims,
    validate_answer,
)

_EVENT_OK_PAYLOAD = {
    "_tool_name": "calculate_event_return",
    "status": "ok",
    "data": {
        "basis": "event",
        "event_id": "news:evt-1",
        "event_date": "2026-07-22",
        "has_post_data": True,
        "baseline_trading_day": "2026-07-21",
        "baseline_close": 100000.0,
        "start_trading_day": "2026-07-21",
        "end_trading_day": "2026-07-29",
        "start_close": 100000.0,
        "end_close": 98000.0,
        "horizons": [
            {"horizon_days": 1, "trading_day": "2026-07-23", "close": 103000.0, "return_pct": 3.0},
        ],
    },
    "sources": [{"source_id": "price:005930:2026-07-21", "source_type": "price"}],
}

_PERIOD_ONLY_PAYLOAD = {
    "_tool_name": "get_stock_prices",
    "status": "ok",
    "data": {
        "quote": {"price": 98000.0, "previous_close": 99000.0},
        "period": {
            "start_trading_day": "2026-06-29",
            "end_trading_day": "2026-07-29",
            "start_close": 90000.0,
            "end_close": 98000.0,
            "return_pct": 8.89,
            "lookback": "1m",
        },
    },
    "sources": [{"source_id": "price:005930:2026-07-29", "source_type": "price"}],
}

_EVENT_NO_POST_PAYLOAD = {
    "_tool_name": "calculate_event_return",
    "status": "no_data",
    "data": {
        "basis": "event",
        "event_id": "news:evt-9",
        "event_date": "2026-07-26",
        "has_post_data": False,
        "baseline_trading_day": "2026-07-24",
        "baseline_close": 100000.0,
        "horizons": [],
    },
    "sources": [],
}


def _errors(answer: str, payloads: list[dict]) -> list[str]:
    return validate_answer(answer, collect_evidence(payloads)).errors


# ── 통과: 사건 근거가 갖춰진 경우 ─────────────────────────────────
def test_event_claim_with_event_evidence_passes():
    errors = _errors(
        "이 뉴스 발표 이후 1거래일 만에 3.0% 상승했습니다(2026-07-21 → 2026-07-23).",
        [_EVENT_OK_PAYLOAD],
    )
    assert not [e for e in errors if "사건" in e]


def test_non_event_period_answer_is_not_checked():
    """일반 기간 질문의 답변은 사건 검증 대상이 아니다."""
    errors = _errors(
        "최근 한 달 동안 8.89% 상승했습니다(2026-06-29 → 2026-07-29).",
        [_PERIOD_ONLY_PAYLOAD],
    )
    assert not [e for e in errors if "사건" in e]


def test_wrong_news_price_percentage_is_replaced_with_price_tool_value():
    payload = {
        "_tool_name": "get_stock_prices",
        "status": "ok",
        "data": {
            "quote": {
                "price": 1_525_000,
                "previous_close": 1_816_000,
                "change_rate_pct": -16.02,
            }
        },
        "sources": [{"source_id": "price:000660:2026-07-28", "source_type": "price"}],
    }
    evidence = collect_evidence([payload])
    answer, changed = sanitize_price_movement_claims(
        "SK하이닉스 주가가 전일 대비 48% 급락했습니다.",
        evidence,
    )
    assert changed is True
    assert "48%" not in answer
    assert "16.02%" in answer
    assert "1,525,000원" in answer


def test_news_only_question_does_not_delete_document_percentage_without_price_evidence():
    evidence = collect_evidence(
        [
            {
                "status": "ok",
                "data": {"news": []},
                "sources": [{"source_id": "n1", "source_type": "news_event"}],
            }
        ]
    )
    answer = "기사에는 관련 종목이 12% 하락했다고 적혀 있습니다."
    sanitized, changed = sanitize_price_movement_claims(answer, evidence)
    assert changed is False
    assert sanitized == answer


def test_price_reason_question_fails_closed_when_price_tool_has_no_evidence():
    evidence = collect_evidence(
        [
            {
                "status": "ok",
                "data": {"news": []},
                "sources": [{"source_id": "n1", "source_type": "news_event"}],
            }
        ]
    )
    answer, changed = sanitize_price_movement_claims(
        "주가가 전일 대비 48% 급락했습니다.",
        evidence,
        require_price_evidence=True,
    )
    assert changed is True
    assert "48%" not in answer
    assert "가격 데이터 조회가 완료되지 않아" in answer


def test_causal_price_news_claim_gets_explicit_limit():
    evidence = collect_evidence(
        [
            {
                "status": "ok",
                "data": {"news": []},
                "sources": [{"source_id": "n1", "source_type": "news_event"}],
            }
        ]
    )
    answer, changed = sanitize_causal_language(
        "오늘 주가가 악재 때문에 하락했습니다.",
        evidence,
    )
    assert changed is True
    assert answer.startswith("뉴스와 주가 움직임이 같은 시기에 확인됐지만")


def test_causal_limit_covers_common_investor_sentiment_wording():
    evidence = collect_evidence(
        [
            {
                "status": "ok",
                "data": {"news": []},
                "sources": [{"source_id": "n1", "source_type": "news_event"}],
            }
        ]
    )
    answer, changed = sanitize_causal_language(
        "주가가 하락했고 외국인 순매도의 영향도 컸으며 투자심리를 악화시켰습니다.",
        evidence,
    )
    assert changed is True
    assert answer.startswith("뉴스와 주가 움직임이 같은 시기에 확인됐지만")


# ── 실패: 이번 결함의 핵심 재현 ───────────────────────────────────
def test_period_return_presented_as_event_return_fails():
    """운영 결함 재현: 최근 1개월 수익률을 '그 뉴스 이후'로 표현하면 검증 실패."""
    errors = _errors(
        "그 뉴스 이후 주가는 8.89% 상승했습니다.",
        [_PERIOD_ONLY_PAYLOAD],
    )
    assert any("일반 기간 수익률만" in e for e in errors)


def test_event_claim_without_any_price_evidence_fails():
    errors = _errors("이 발표 후 주가가 3% 올랐습니다.", [])
    assert any("사건 전후 주가 계산 근거가 없음" in e for e in errors)


def test_event_claim_with_no_post_data_fails():
    """발표 후 거래일이 없는데 수치를 주장하면 실패."""
    errors = _errors(
        "이 뉴스 이후 주가가 2.5% 하락했습니다.",
        [_EVENT_NO_POST_PAYLOAD],
    )
    assert any("사건" in e for e in errors)


def test_no_data_state_answer_passes():
    """데이터 없음을 그대로 답하면(수치 주장 없음) 위반이 아니다."""
    errors = _errors(
        "2026-07-26 발표 이후 확정 거래일 데이터가 아직 없어 계산할 수 없습니다.",
        [_EVENT_NO_POST_PAYLOAD],
    )
    assert not [e for e in errors if "사건" in e]


def test_clarification_answer_passes():
    errors = _errors(
        "어떤 사건을 기준으로 볼지 정해주세요. 2026-07-22 HBM 공급계약, 2026-07-18 관세 발표.",
        [],
    )
    assert not [e for e in errors if "사건" in e]


# ── 날짜 오탐 회귀(같은 호출 경로에서 함께 발견) ──────────────────
def test_dates_in_clarification_are_not_financial_numbers():
    """사건 후보를 날짜와 함께 되묻는 답변이 '근거 없는 재무 숫자'로 오탐되지 않는다."""
    errors = _errors(
        "서로 다른 뉴스 사건이 여러 개 있습니다.\n"
        "1. 2026-07-25 · 엔비디아 본사 회동\n"
        "2. 2026-07-24 · AI 서밋 악수\n",
        [],
    )
    assert not [e for e in errors if "재무성 숫자" in e]


def test_korean_date_forms_are_not_financial_numbers():
    errors = _errors("2026년 7월 25일 발표된 사건입니다. 2025년 3분기 자료를 참고하세요.", [])
    assert not [e for e in errors if "재무성 숫자" in e]


def test_real_unsupported_number_still_flagged():
    """날짜 제외가 실제 근거 없는 숫자까지 통과시키지는 않는다."""
    errors = _errors("영업이익은 12조 3456억원입니다.", [])
    assert any("재무성 숫자" in e for e in errors)


_NEWS_PAYLOAD = {
    "_tool_name": "search_news",
    "status": "ok",
    "data": {"news": [{"source_id": "news_cluster:7164", "title": "반도체주 하락"}]},
    "sources": [{"source_id": "news_cluster:7164", "source_type": "news_event"}],
}


def test_numbers_quoted_from_news_are_grounded_by_the_article():
    """뉴스 본문 수치(지수 등락률 등)는 그 기사가 근거다 — 재무 Tool 부재로 실패시키지 않는다."""
    errors = _errors(
        "어제 필라델피아 반도체 지수가 4.25% 하락했고 마이크론은 7% 하락했습니다.",
        [_NEWS_PAYLOAD],
    )
    assert not [e for e in errors if "재무성 숫자" in e]


def test_stock_code_is_not_a_financial_number():
    """존재하지 않는 종목코드를 안내하는 답변이 숫자 주장으로 오탐되지 않는다."""
    errors = _errors("종목 코드 999999는 존재하지 않아 정보를 제공할 수 없습니다.", [])
    assert not [e for e in errors if "재무성 숫자" in e]


def test_leading_zero_stock_code_excluded():
    errors = _errors("005930 종목은 조회할 수 있습니다.", [])
    assert not [e for e in errors if "재무성 숫자" in e]


def test_six_digit_price_is_still_checked():
    """6자리 가격까지 종목코드로 오인해 통과시키지 않는다."""
    errors = _errors("주가는 123456원입니다.", [])
    assert any("재무성 숫자" in e for e in errors)


# ── 근거 수집 계약 ────────────────────────────────────────────────
def test_evidence_collects_event_fields():
    ev = collect_evidence([_EVENT_OK_PAYLOAD])
    assert ev.has_event_return is True
    assert ev.event_ids == {"news:evt-1"}
    assert ev.event_dates == {"2026-07-22"}
    assert "2026-07-21" in ev.event_trading_days
    assert "2026-07-23" in ev.event_trading_days


def test_no_data_event_is_not_evidence():
    ev = collect_evidence([_EVENT_NO_POST_PAYLOAD])
    assert ev.has_event_return is False


def test_period_payload_marks_period_return_only():
    ev = collect_evidence([_PERIOD_ONLY_PAYLOAD])
    assert ev.has_period_return is True
    assert ev.has_event_return is False
