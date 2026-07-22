"""QueryPlan 규칙 라우팅 단위 테스트 (SPEC §9). 외부 호출 없음."""

from __future__ import annotations

from app.rag.query_plan import build_query_plan


def test_number_question_sets_financials():
    p = build_query_plan("삼성전자 영업이익이 얼마야?", stock_code="005930")
    assert p.need_financials is True
    assert p.stock_code == "005930"


def test_mixed_question_sets_both():
    p = build_query_plan("영업이익이 얼마고 왜 늘었어?", stock_code="005930")
    assert p.need_financials is True
    assert p.need_documents is True  # '왜' 설명 신호


def test_term_question_sets_terms():
    p = build_query_plan("ADR이 뭐야?")
    assert p.need_terms is True


def test_correction_question():
    p = build_query_plan("정정 전과 정정 후 뭐가 바뀌었어?", stock_code="000660")
    assert p.need_correction is True
    assert p.need_documents is True


def test_stock_priority_ui_over_current():
    p = build_query_plan("영업이익 얼마?", stock_code="005930", current_stock_code="000660")
    assert p.stock_code == "005930"


def test_stock_from_current_when_no_ui():
    p = build_query_plan("영업이익 얼마?", current_stock_code="000660")
    assert p.stock_code == "000660"


def test_stock_from_six_digit_in_text():
    p = build_query_plan("034020 매출 얼마?")
    assert p.stock_code == "034020"


def test_no_stock_stays_none():
    p = build_query_plan("이게 무슨 뜻이야?")
    assert p.stock_code is None
    assert p.need_terms is True
