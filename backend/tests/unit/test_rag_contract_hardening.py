import unicodedata
from datetime import datetime

from app.agent.runtime import _normalize_financial_request
from app.agent.tools.disclosures import resolve_disclosure_event_types
from app.agent.tools.prices import resolve_price_lookback
from app.agent.tools.reports import resolve_report_broker
from app.agent.validator import (
    ToolEvidence,
    collect_evidence,
    sanitize_answer_style,
    sanitize_causal_language,
    sanitize_conflicting_document_price_claims,
    sanitize_price_movement_claims,
    sanitize_unfinalized_close_claim,
)
from app.services.agent_qa import AgentQaService
from app.services.stock_context_safety import decision_from_semantic_stock_reference
from app.services.stock_prices import market_status_at


def test_context_answer_removes_only_repetitive_opening():
    answer, changed = sanitize_answer_style("쉽게 말해, 매출은 늘었고 비용도 증가했습니다.")
    assert changed
    assert answer == "매출은 늘었고 비용도 증가했습니다."


def test_causal_sanitizer_removes_unsupported_direct_cause_sentence():
    evidence = ToolEvidence(has_documents=True)
    answer, changed = sanitize_causal_language(
        "뉴스 때문에 주가가 5% 하락했습니다. 회사는 신규 투자를 발표했습니다.",
        evidence,
    )
    assert changed
    assert "뉴스 때문에" not in answer
    assert "신규 투자를 발표" in answer
    assert "직접적인 원인이라고 단정할 수는 없습니다" in answer


def test_causal_sanitizer_removes_cause_sentence_after_movement_sentence():
    evidence = ToolEvidence(has_documents=True)
    answer, changed = sanitize_causal_language(
        "주가가 14% 급락했습니다. 해외 경쟁사 상장이 투자심리를 악화시켰습니다.",
        evidence,
    )
    assert changed
    assert "주가가 14% 급락" in answer
    assert "투자심리를 악화" not in answer


def test_conflicting_news_directions_are_not_combined_without_price_tool():
    evidence = ToolEvidence(has_documents=True)
    answer, changed = sanitize_conflicting_document_price_claims(
        "한 기사는 주가가 3% 상승했다고 전했습니다. 다른 기사는 5% 급락했다고 전했습니다.",
        evidence,
    )
    assert changed
    assert "서로 엇갈려" in answer
    assert "3%" not in answer
    assert "5%" not in answer


def test_news_summary_does_not_receive_repetitive_causal_notice():
    evidence = ToolEvidence(has_documents=True)
    answer, changed = sanitize_causal_language(
        ("삼성전자와 SK하이닉스 주가가 하락했습니다. 중국 업체 상장이 투자심리를 악화시켰습니다."),
        evidence,
        include_notice=False,
    )
    assert changed
    assert "직접적인 원인이라고 단정" not in answer


def test_news_explanation_does_not_emit_document_direction_conflict_notice():
    evidence = ToolEvidence(has_documents=True)
    original = "한 기사는 상승을, 다른 기사는 하락을 언급했습니다."
    answer, changed = sanitize_conflicting_document_price_claims(
        original,
        evidence,
        enabled=False,
    )
    assert changed is False
    assert answer == original


def test_event_return_mismatch_does_not_claim_price_lookup_failed():
    evidence = ToolEvidence(
        has_price=True,
        has_event_return=True,
        price_change_rates={2.31, 13.85, 18.77},
    )
    answer, changed = sanitize_price_movement_claims(
        "발표 후 주가는 99% 하락했습니다.",
        evidence,
    )
    assert changed
    assert "가격 데이터 조회가 완료되지 않아" not in answer
    assert "99%" not in answer


def test_unfinalized_today_close_is_replaced_with_quote_contract():
    evidence = ToolEvidence(
        has_price=True,
        current_price=218_000,
        price_kind="current",
        market_status="after_market",
        price_as_of="2026-07-28T19:59:59+09:00",
    )
    answer, changed = sanitize_unfinalized_close_claim(
        "오늘 종가는 218,000원입니다.",
        evidence,
        asks_today_close=True,
    )
    assert changed
    assert "확정 종가는 아직 확인되지 않았습니다" in answer
    assert "장후거래 중" in answer
    assert "218,000원" in answer


def test_generic_flow_defaults_to_one_month_but_point_price_does_not():
    assert resolve_price_lookback("주가 흐름 보여줘", None) == "1m"
    assert resolve_price_lookback("현재가 알려줘", None) is None
    assert resolve_price_lookback("최근 1년 주가 흐름", "1y") == "1y"


def test_market_status_distinguishes_regular_and_after_market():
    assert market_status_at(datetime.fromisoformat("2026-07-28T10:00:00+09:00")) == "regular_open"
    assert market_status_at(datetime.fromisoformat("2026-07-28T19:59:00+09:00")) == "after_market"


def test_report_broker_handles_decomposed_unicode():
    question = "한화투자증권 리포트의 목표주가 알려줘"
    decomposed = unicodedata.normalize("NFD", question)
    assert resolve_report_broker(decomposed) == "한화투자증권"


def test_disclosure_question_routes_to_structured_event():
    assert resolve_disclosure_event_types("자사주 처분 수량은 얼마야?") == [
        "treasury_stock_disposal"
    ]
    assert resolve_disclosure_event_types("주당 배당금 알려줘") == ["dividend_matter"]


def test_financial_request_normalizes_alias_and_quarter_contract():
    account, accounts, amount_type, fs_div = _normalize_financial_request(
        "2025년 3분기 단독 순이익은?",
        "순이익",
        None,
        "cumulative",
        "OFS",
    )
    assert account == "당기순이익"
    assert accounts == []
    assert amount_type == "quarter"
    assert fs_div == "CFS"


def test_person_and_report_publisher_are_not_extra_stock_targets():
    person = decision_from_semantic_stock_reference(
        relation="multiple",
        company_names=["SK하이닉스", "이재명 대통령"],
        selected_stock_code="000660",
        question="SK하이닉스와 이재명 대통령 관련 뉴스 알려줘",
    )
    assert person.allowed
    broker = decision_from_semantic_stock_reference(
        relation="multiple",
        company_names=["현대차", "한화투자증권"],
        selected_stock_code="005380",
        question="한화투자증권 현대차 리포트 알려줘",
    )
    assert broker.allowed


def test_primary_report_payload_preserves_stated_target_price_evidence():
    payload = AgentQaService._primary_source_payload(
        {
            "source_id": "chunk-1",
            "source_type": "research_report",
            "stock_code": "000660",
            "title": "전망",
            "publisher": "하나증권",
            "published_at": "2026-06-26",
            "target_price": 3_600_000,
            "target_price_status": "stated",
            "target_price_currency": "KRW",
            "investment_opinion": "BUY",
        }
    )
    evidence = collect_evidence([payload])
    assert evidence.stated_target_prices == {3_600_000}
    assert evidence.brokers == {"하나증권"}
