"""QueryPlan 규칙 라우팅 단위 테스트 (SPEC §9). 외부 호출 없음."""

from __future__ import annotations

from app.rag.query_plan import build_query_plan


def test_number_question_sets_financials():
    p = build_query_plan("삼성전자 영업이익이 얼마야?", stock_code="005930")
    assert p.need_financials is True
    assert p.stock_code == "005930"


def test_pure_number_question_skips_documents():
    """순수 숫자 질문은 SQL 만. 문서(뉴스) 검색을 켜지 않는다(임베딩 호출 방지)."""
    p = build_query_plan("삼성전자 2025년 영업이익 얼마?", stock_code="005930")
    assert p.need_financials is True
    assert p.need_documents is False
    assert p.need_terms is False


def test_pure_number_question_batch_no_documents():
    """설명 신호 없는 재무 수치 질문은 SQL 만(문서 검색 끔). 문장 하드코딩 아님."""
    for q in ("배당 얼마야?", "매출 몇이야?", "자산총계 얼마?", "순이익 규모"):
        p = build_query_plan(q, stock_code="005930")
        assert p.need_financials is True, q
        assert p.need_documents is False, q
        assert p.need_reports is False, q


def test_target_price_is_report_intent_not_financial():
    """'목표주가'는 증권사 예측치 → report intent. financial(SQL)·뉴스를 켜지 않는다."""
    p = build_query_plan("목표주가 얼마?", stock_code="005930")
    assert p.need_reports is True
    assert p.need_financials is False
    assert p.need_documents is False


def test_pure_term_question_skips_documents():
    """순수 용어 질문은 용어 조회만. 문서 검색을 켜지 않는다."""
    p = build_query_plan("PER이 뭐야?")
    assert p.need_terms is True
    assert p.need_documents is False
    assert p.need_financials is False


def test_mixed_question_sets_both():
    p = build_query_plan("영업이익이 얼마고 왜 늘었어?", stock_code="005930")
    assert p.need_financials is True
    assert p.need_documents is True  # '왜' 설명 신호


def test_number_with_impact_signal_sets_documents():
    """숫자 + 영향/전망 등 설명 신호가 있으면 문서 검색을 켠다."""
    p = build_query_plan("영업이익 감소가 주가에 어떤 영향을 줬어?", stock_code="005930")
    assert p.need_financials is True
    assert p.need_documents is True


def test_pure_news_question_sets_documents():
    """사실 신호(숫자/용어) 없는 자연어 질문은 기본 뉴스 검색을 켠다."""
    p = build_query_plan("삼성전자 최근 소식 알려줘.", stock_code="005930")
    assert p.need_financials is False
    assert p.need_terms is False
    assert p.need_documents is True


def _route(q, sc="005930"):
    p = build_query_plan(q, stock_code=sc)
    return (p.need_financials, p.need_documents, p.need_reports)


def test_report_intent_synonyms_and_wording():
    """report intent: 동의어·어순·복합 표현 모두 리포트만 켠다(SQL·뉴스 미호출)."""
    for q in (
        "삼성전자 목표주가",
        "목표가는?",
        "증권사 목표가는 얼마",
        "투자의견 어때",
        "증권사 분석 정리해줘",
        "애널리스트 컨센서스",
        "리포트 전망 어떻게 봐",
        "목표주가 상향됐어?",
    ):
        fin, news, rep = _route(q)
        assert rep is True, q
        assert fin is False and news is False, q  # 과호출 없음


def test_intents_are_independent_combinations():
    """여러 의도가 있으면 해당 신호만 조합된다."""
    # financial + report
    assert _route("영업이익이랑 목표주가 둘 다") == (True, False, True)
    assert _route("매출이랑 증권사 전망") == (True, False, True)
    # news + report
    assert _route("실적 악화 원인이랑 향후 전망") == (False, True, True)
    assert _route("최근 이슈랑 목표주가") == (False, True, True)
    # financial + news + report
    assert _route("영업이익 얼마고 왜 줄었고 증권사 전망은?") == (True, True, True)


def test_non_report_questions_skip_reports():
    """부정 사례: 순수 숫자·뉴스·용어 질문은 리포트 검색을 켜지 않는다."""
    assert _route("2025년 영업이익 얼마?") == (True, False, False)
    assert _route("삼성전자 최근 뉴스") == (False, True, False)
    assert build_query_plan("PER이 뭐야?").need_reports is False


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
