"""목표주가 추출기 단위 테스트 (prompt.md §3·§10). 실제 리포트 표 형식 기반.

핵심 안전 규칙 검증:
- report_date 일치 행만 현재값 (과거 변동이력 사용 금지)
- 매출/영업이익/EPS 오인 금지
- 목표주가 없으면 not_stated, 라벨만 있고 값 없으면 parse_failed
- 복수 후보 충돌 시 ambiguous, 범위 임의 합성 없음
"""

from __future__ import annotations

from datetime import date

from app.rag.target_price_extractor import (
    extract_from_history_table,
    extract_from_page_text,
    extract_target_price,
)


# 실제 미래에셋 '투자의견 및 목표주가 변동추이' 표 형식(감사 [B]에서 확인)
def _mirae_history_rows():
    return [
        ["제시일자", "투자의견", "목표주가(원)", "괴리율"],
        ["2026.05.04", "매수", "320,000", "-"],
        ["2026.03.18", "매수", "300,000", "-32.55"],
        ["2026.02.23", "매수", "275,000", "-29.93"],
    ]


def test_history_table_uses_report_date_row_not_latest_or_max():
    # report_date=2026-03-18 → 그 행(300,000)만 현재값. 최신(320,000)·최대 아님.
    res = extract_from_history_table(
        headers=["투자의견 및 목표주가 변동추이"],
        rows=_mirae_history_rows(),
        report_date=date(2026, 3, 18),
    )
    assert res is not None
    assert res.status == "stated"
    assert res.value == 300_000
    assert res.effective_date == date(2026, 3, 18)


def test_history_table_report_date_is_top_row():
    res = extract_from_history_table(
        headers=["변동추이"], rows=_mirae_history_rows(), report_date=date(2026, 5, 4)
    )
    assert res.status == "stated" and res.value == 320_000


def test_history_table_no_matching_date_returns_none():
    # report_date 가 표에 없으면 이 소스로 확정 불가 → None(호출부가 페이지 텍스트로)
    res = extract_from_history_table(
        headers=["변동추이"], rows=_mirae_history_rows(), report_date=date(2025, 1, 1)
    )
    assert res is None


def test_history_table_ambiguous_when_same_date_conflicting_values():
    rows = [
        ["제시일자", "목표주가"],
        ["2026.05.04", "320,000"],
        ["2026.05.04", "300,000"],  # 같은 날 다른 값 → 확정 불가
    ]
    res = extract_from_history_table(["제시일자", "목표주가"], rows, date(2026, 5, 4))
    assert res.status == "ambiguous"
    assert len(res.candidates) == 2


def test_page_text_label_adjacent_value():
    pages = [{"page_number": 1, "plain_text": "삼성전자 투자의견 매수 목표주가 95,000원 상향"}]
    res = extract_from_page_text(pages, date(2026, 1, 12))
    assert res.status == "stated" and res.value == 95_000 and res.source_page == 1


def test_page_text_does_not_confuse_revenue_or_op_profit():
    # '영업이익 57조', '매출 133조' 같은 큰 수를 목표주가로 오인하지 않는다.
    pages = [{"page_number": 3, "plain_text": "2026년 영업이익 57,230,000 매출액 133,870,000"}]
    res = extract_from_page_text(pages, date(2026, 5, 4))
    assert res.status == "not_stated"  # 목표주가 라벨 자체가 없음


def test_page_text_label_without_value_is_parse_failed():
    pages = [{"page_number": 2, "plain_text": "목표주가를 제시한다. (표 참조)"}]
    res = extract_from_page_text(pages, date(2026, 5, 4))
    assert res.status == "parse_failed"


def test_page_text_history_only_is_ambiguous():
    pages = [{"page_number": 8, "plain_text": "목표주가 변동추이 제시일자 괴리율 표"}]
    res = extract_from_page_text(pages, date(2026, 5, 4))
    assert res.status == "ambiguous"


def test_page_text_no_label_is_not_stated():
    pages = [{"page_number": 1, "plain_text": "메모리 업황이 개선되고 있다."}]
    res = extract_from_page_text(pages, date(2026, 5, 4))
    assert res.status == "not_stated"


def test_extract_prefers_table_then_page():
    tables = [
        {
            "headers": ["목표주가 변동추이"],
            "rows": _mirae_history_rows(),
            "page_number": 10,
        }
    ]
    pages = [{"page_number": 1, "plain_text": "목표주가 99,000원"}]  # 다른 값
    res = extract_target_price(tables, pages, date(2026, 5, 4))
    # 표(변동추이, report_date 일치)가 우선 → 320,000
    assert res.status == "stated" and res.value == 320_000
    assert res.source_page == 10


def test_extract_falls_back_to_page_when_table_has_no_matching_date():
    tables = [{"headers": ["목표주가 변동추이"], "rows": _mirae_history_rows(), "page_number": 10}]
    pages = [{"page_number": 1, "plain_text": "목표주가 88,000원 제시"}]
    res = extract_target_price(tables, pages, date(2099, 1, 1))
    assert res.status == "stated" and res.value == 88_000 and res.source_page == 1


def test_extract_not_stated_when_nothing():
    res = extract_target_price([], [{"page_number": 1, "plain_text": "업황 개선"}], None)
    assert res.status == "not_stated"


# ── 실제 리포트 표지 형식(감사 [3] 표본) 회귀 방지 ──
def test_real_cover_comma_with_qualifier_token():
    # '목표주가(12M) 480,000원(유지)' — 라벨과 값 사이 (12M) 토큰
    txt = "Buy 목표주가(12M) 480,000원(유지) 종가(2026.07.07) 296,000원 상승여력 62.2%"
    r = extract_from_page_text([{"page_number": 1, "plain_text": txt}], date(2026, 7, 8))
    assert r.status == "stated" and r.value == 480_000


def test_real_cover_han_man_won_unit():
    # '목표주가 48만원' — 한글 만 단위
    txt = "투자의견 BUY, 목표주가 48만원을 유지한다."
    r = extract_from_page_text([{"page_number": 1, "plain_text": txt}], date(2026, 7, 8))
    assert r.status == "stated" and r.value == 480_000


def test_real_cover_target_then_current_price_not_confused():
    # '목표주가 560,000원 ... 현재주가 296,000원' — 목표가(앞)만, 현재가(뒤) 무시
    txt = "STRONG BUY 목표주가 560,000원(유지) 현재주가 296,000원(7/7)"
    r = extract_from_page_text([{"page_number": 1, "plain_text": txt}], date(2026, 7, 8))
    assert r.status == "stated" and r.value == 560_000


def test_current_price_alone_is_not_target():
    # 목표주가 라벨 없이 현재주가만 → 목표가로 쓰지 않는다
    txt = "현재주가 296,000원 상승여력 62%"
    r = extract_from_page_text([{"page_number": 1, "plain_text": txt}], date(2026, 7, 8))
    assert r.status == "not_stated"
