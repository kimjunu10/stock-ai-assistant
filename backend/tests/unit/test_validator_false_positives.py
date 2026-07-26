"""Phase 8 1차 교정: 검증기 오탐 회귀 테스트 (LLM·DB 호출 없음).

baseline 에서 실제로 관찰된 오탐을 고정한다.
오탐을 없애되 진짜 환각은 계속 차단해야 하므로, 양방향을 모두 검증한다.
"""

from __future__ import annotations

import unicodedata

from app.agent.validator import (
    collect_evidence,
    sanitize_answer,
    validate_answer,
)


def _report_payload(broker: str, target_price: int | None = 4_200_000, status: str = "stated"):
    rp: dict = {"broker": broker, "target_price_status": status}
    if target_price is not None:
        rp["target_price"] = target_price
    return {
        "status": "ok",
        "_tool_name": "search_research_reports",
        "data": {"reports": [rp]},
    }


# ─────────────── A. 증권사명 유니코드 정규화 ───────────────


def test_nfd_publisher_matches_nfc_answer():
    """운영 결함: DB publisher 가 NFD 라 같은 증권사도 '없는 증권사'로 판정됐다.

    report-01(미래에셋증권) 등에서 근거 있는 답변이 통째로 지워졌다.
    """
    nfd = unicodedata.normalize("NFD", "미래에셋증권")
    assert nfd != "미래에셋증권"  # 전제: 코드포인트가 다르다

    ev = collect_evidence([_report_payload(nfd)])
    answer = "미래에셋증권은 목표주가를 4,200,000원으로 제시했습니다."

    assert validate_answer(answer, ev).errors == []
    cleaned, changed = sanitize_answer(answer, ev)
    assert changed is False
    assert "4,200,000" in cleaned


def test_publisher_whitespace_difference_matches():
    ev = collect_evidence([_report_payload("미래에셋 증권")])
    answer = "미래에셋증권은 목표주가를 4,200,000원으로 제시했습니다."
    assert validate_answer(answer, ev).errors == []


def test_unknown_broker_still_blocked():
    """근거에 없는 증권사는 계속 차단해야 한다(느슨한 비교로 흘리지 않는다)."""
    ev = collect_evidence([_report_payload(unicodedata.normalize("NFD", "미래에셋증권"))])
    answer = "한국투자증권은 목표주가를 5,000,000원으로 제시했습니다."

    errors = validate_answer(answer, ev).errors
    assert any("없는 증권사" in e for e in errors)
    _, changed = sanitize_answer(answer, ev)
    assert changed is True


def test_unsupported_target_price_still_blocked():
    """근거 증권사라도 Tool 결과에 없는 목표주가는 차단."""
    ev = collect_evidence([_report_payload("미래에셋증권", target_price=4_200_000)])
    answer = "미래에셋증권은 목표주가를 9,999,999원으로 제시했습니다."
    errors = validate_answer(answer, ev).errors
    assert any("목표주가" in e for e in errors)


def test_non_stated_target_price_not_treated_as_evidence():
    """target_price_status 가 stated 가 아니면 근거로 인정하지 않는다."""
    ev = collect_evidence([_report_payload("미래에셋증권", 4_200_000, status="inferred")])
    answer = "미래에셋증권은 목표주가를 4,200,000원으로 제시했습니다."
    assert any("목표주가" in e for e in validate_answer(answer, ev).errors)


# ─────────────── C. 일반 숫자 오탐 ───────────────


def _term_payload():
    return {
        "status": "ok",
        "_tool_name": "lookup_financial_term",
        "data": {"term": "공매도", "definition": "..."},
    }


def test_example_numbers_in_term_explanation_not_flagged():
    """운영 결함(term-01): 용어 설명의 가정 예시 숫자가 '근거 없는 재무 숫자'로 잡혔다."""
    ev = collect_evidence([_term_payload()])
    answer = (
        "공매도는 주식을 빌려 먼저 파는 투자 방법입니다. "
        "예를 들어, 주당 15,000원에 빌린 주식을 10,000원에 사서 갚으면 차익이 생깁니다."
    )
    assert not any("재무성 숫자" in e for e in validate_answer(answer, ev).errors)


def test_unsupported_stock_code_not_flagged_as_number():
    """운영 결함(na-02): 존재하지 않는 종목코드 '999999' 가 재무 숫자로 오인됐다."""
    ev = collect_evidence([])
    answer = '죄송하지만, "999999" 종목 코드는 지원하지 않는 종목 코드입니다.'
    assert not any("재무성 숫자" in e for e in validate_answer(answer, ev).errors)


def test_page_and_count_numbers_not_flagged():
    ev = collect_evidence([_term_payload()])
    answer = "관련 내용은 리포트 1234페이지에 있으며 총 5000건이 조회되었습니다."
    assert not any("재무성 숫자" in e for e in validate_answer(answer, ev).errors)


def test_date_numbers_not_flagged():
    ev = collect_evidence([])
    answer = "2026년 7월 25일 기준이며 2026-07-24 에도 같았습니다."
    assert not any("재무성 숫자" in e for e in validate_answer(answer, ev).errors)


def test_real_financial_claim_without_evidence_still_flagged():
    """근거 없는 회사 재무 숫자는 계속 차단해야 한다(오탐 제거의 반대급부 확인)."""
    ev = collect_evidence([])
    answer = "삼성전자의 2025년 영업이익은 43조 6,010억원입니다."
    assert any("재무성 숫자" in e for e in validate_answer(answer, ev).errors)


def test_example_sentence_does_not_hide_real_claim_elsewhere():
    """예시 문장을 빼더라도 다른 문장의 근거 없는 재무 주장은 잡아야 한다."""
    ev = collect_evidence([_term_payload()])
    answer = (
        "예를 들어 주당 15,000원이라고 합시다. 삼성전자의 2025년 영업이익은 43조 6,010억원입니다."
    )
    assert any("재무성 숫자" in e for e in validate_answer(answer, ev).errors)
