"""Phase 8 1차 교정: Tool 입력 계약 회귀 테스트 (LLM·DB 호출 없음).

baseline 에서 관찰된 입력 계약 결함을 고정한다:
- 공시 event_types 에 한국어를 넣어 no_data 가 나던 문제
- '단독 3분기'를 별도재무제표(OFS)로 오해하던 문제
"""

from __future__ import annotations

import json
from typing import get_args

import pytest
from pydantic import ValidationError

from app.agent.runtime import build_tools
from app.agent.tools.disclosures import DisclosureEventType, DisclosureValuesInput


def _tool(name: str):
    return {t.name: t for t in build_tools()}[name]


def _openai_schema(name: str) -> str:
    from langchain_core.utils.function_calling import convert_to_openai_tool

    return json.dumps(convert_to_openai_tool(_tool(name)), ensure_ascii=False)


# ─────────────── 공시 event_types 계약 ───────────────

# DB(structured_disclosures.event_type)에 실제 존재하는 값.
_DB_EVENT_TYPES = {
    "dividend_matter",
    "treasury_stock_status",
    "treasury_stock_acquisition",
    "treasury_stock_disposal",
    "stock_total_status",
    "capital_change_status",
    "paid_in_capital_increase",
    "overseas_listing",
    "overseas_listing_decision",
}


def test_event_type_literal_matches_db_values():
    """스키마 허용값이 DB 실제 값과 정확히 일치해야 한다."""
    assert set(get_args(DisclosureEventType)) == _DB_EVENT_TYPES


def test_korean_event_type_rejected_by_schema():
    """운영 결함: event_types=['배당'] 이 통과해 no_data 를 만들었다."""
    with pytest.raises(ValidationError):
        DisclosureValuesInput(stock_code="005930", event_types=["배당"])


def test_valid_event_type_accepted():
    inp = DisclosureValuesInput(stock_code="005930", event_types=["dividend_matter"])
    assert inp.event_types == ["dividend_matter"]


def test_empty_event_types_allowed():
    """유형 미지정은 정상(전체 최신 공시 조회)."""
    assert DisclosureValuesInput(stock_code="005930").event_types == []


def test_event_type_enum_exposed_to_model():
    """모델이 보는 스키마에 유효값과 한국어 대응이 실려야 추측하지 않는다."""
    schema = _openai_schema("get_disclosure_values")
    for value in _DB_EVENT_TYPES:
        assert value in schema, f"{value} 가 모델 스키마에 없음"
    assert "배당" in schema  # 사용자 표현 → 코드 대응 안내
    assert "한국어" in schema  # 한국어 금지 명시


def test_invalid_event_type_returns_input_error_not_no_data():
    """허용되지 않은 값은 '데이터 없음'이 아니라 입력 오류로 구분해야 한다.

    no_data 로 뭉개면 모델이 "공시가 없다"고 잘못 답한다.
    """

    class _Ctx:
        services = object()
        stock_code = "005930"

    class _RT:
        context = _Ctx()

    out = json.loads(
        _tool("get_disclosure_values").func(
            stock_code="005930", runtime=_RT(), event_types=["배당"]
        )
    )
    assert out["status"] == "error"
    # ToolResult 는 안내 문구를 warnings 로 싣는다(내부 예외 비노출 계약).
    assert any("dividend_matter" in w for w in out.get("warnings", []))


# ─────────────── 재무 기간·별도 계약 ───────────────


def test_financial_tool_documents_period_and_fs_div_rules():
    """'단독'을 별도재무제표로 오해하지 않도록 계약이 문서화돼야 한다(fin-04 결함)."""
    schema = _openai_schema("get_financial_facts")
    assert "point_in_time" in schema and "cumulative" in schema and "quarter" in schema
    # 단독 ≠ 별도(OFS)
    assert "단독" in schema and "별도" in schema
    assert "OFS" in schema


def test_financial_tool_documents_ambiguous_quarter_policy():
    """'3분기 영업이익'의 누적/3개월 모호성을 몰래 한쪽으로 강제하지 않는다."""
    schema = _openai_schema("get_financial_facts")
    assert "되묻" in schema or "확인" in schema


def test_eight_tools_still_registered():
    """계약 변경이 Tool 구성을 바꾸지 않았는지 확인."""
    assert len(build_tools()) == 8


# ─────────────── 증권사 필터 유니코드 ───────────────


def test_broker_filter_matches_across_unicode_forms():
    """운영 결함: DB broker 가 NFD 라 'IBK투자증권' 필터가 0건을 반환했다."""
    import unicodedata

    from app.services.research_reports import _norm_broker

    nfd = unicodedata.normalize("NFD", "IBK투자증권")
    assert nfd != "IBK투자증권"  # 전제
    assert _norm_broker("IBK투자증권") in _norm_broker(nfd)
    assert _norm_broker("IBK 투자증권") in _norm_broker(nfd)


def test_broker_filter_still_excludes_other_brokers():
    from app.services.research_reports import _norm_broker

    assert _norm_broker("키움증권") not in _norm_broker("IBK투자증권")
