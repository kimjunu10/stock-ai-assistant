from __future__ import annotations

import json

import pytest

from app.agent.context import ToolServices
from app.agent.runtime import build_tools
from app.agent.tools.common import ok
from app.services.relevance import STOCK_MENTION_RULES
from app.services.stock_context_safety import (
    decision_from_semantic_stock_reference,
    natural_company_candidates,
    validate_execution_stock_context,
    validate_input_source_stock_context,
    validate_question_stock_context,
)
from app.sources.prices import SUPPORTED_STOCK_CODES


class _Runtime:
    def __init__(self):
        self.context = type(
            "Context",
            (),
            {
                "services": ToolServices(
                    facts=object(),
                    retriever=None,
                    reports=None,
                ),
                "stock_code": "005930",
                "stock_context_events": [],
            },
        )()


def test_supported_stock_codes_and_existing_name_rules_stay_in_sync():
    assert set(STOCK_MENTION_RULES) == set(SUPPORTED_STOCK_CODES)


def test_question_without_company_uses_selected_stock():
    decision = validate_question_stock_context("올해 실적 알려줘", "005930")

    assert decision.allowed
    assert decision.selected_stock_code == "005930"
    assert decision.mentions == ()


def test_same_supported_company_is_allowed():
    decision = validate_question_stock_context("삼성전자 올해 실적 알려줘", "005930")

    assert decision.allowed
    assert [mention.stock_code for mention in decision.mentions] == ["005930"]


def test_different_supported_company_is_blocked_before_agent():
    decision = validate_question_stock_context("현대차 올해 실적 알려줘", "005930")

    assert not decision.allowed
    assert decision.error_code == "STOCK_CONTEXT_MISMATCH"
    assert "종목을 현대차로 변경" in (decision.message or "")


def test_natural_company_candidate_is_deferred_to_semantic_classification():
    for question in (
        "애플 올해 실적 알려줘",
        "애플 알려줘",
        "NVIDIA 올해 실적 알려줘",
        "Tesla 올해 실적 알려줘",
    ):
        decision = validate_question_stock_context(question, "005930")
        assert decision.allowed, question
        assert natural_company_candidates(question), question


def test_semantic_multiple_company_result_is_blocked():
    for question in ("삼성전자와 애플 실적 비교해줘", "삼성전자와 애플 비교해줘"):
        decision = validate_question_stock_context(question, "005930")
        semantic_decision = decision_from_semantic_stock_reference(
            relation="multiple",
            company_names=["삼성전자", "애플"],
            selected_stock_code="005930",
        )

        assert decision.allowed
        assert not semantic_decision.allowed
        assert semantic_decision.error_code == "MULTI_STOCK_NOT_SUPPORTED"
        assert semantic_decision.message == "현재 화면에서는 한 종목씩 조회할 수 있습니다."


def test_semantic_other_company_result_is_blocked_as_unsupported():
    decision = decision_from_semantic_stock_reference(
        relation="other",
        company_names=["애플"],
        selected_stock_code="005930",
    )

    assert not decision.allowed
    assert decision.error_code == "UNSUPPORTED_STOCK"
    assert "현재 애플은 지원하지 않는 종목" in (decision.message or "")


def test_explicit_unsupported_ticker_is_blocked_without_model_classification():
    decision = validate_question_stock_context("$AAPL 주가 알려줘", "005930")

    assert not decision.allowed
    assert decision.error_code == "UNSUPPORTED_STOCK"
    assert decision.mentions[0].name.upper() == "AAPL"


def test_multiple_supported_companies_are_blocked():
    decision = validate_question_stock_context("삼성전자와 현대차 비교해줘", "005930")

    assert not decision.allowed
    assert decision.error_code == "MULTI_STOCK_NOT_SUPPORTED"


def test_explicit_tool_stock_mismatch_blocks_final_answer():
    tool_call = type(
        "Call",
        (),
        {"name": "get_financial_facts", "stock_code": "000660"},
    )()

    violation = validate_execution_stock_context(
        selected_stock_code="005930",
        runtime_stock_code="005930",
        tool_calls=[tool_call],
        tool_payloads=[],
    )

    assert violation is not None
    assert violation.failed_layer == "tool_call_trace"


def test_source_stock_mismatch_blocks_final_answer():
    violation = validate_execution_stock_context(
        selected_stock_code="005930",
        runtime_stock_code="005930",
        tool_calls=[],
        tool_payloads=[
            {
                "status": "ok",
                "sources": [
                    {
                        "source_id": "000660/2025/영업이익",
                        "stock_code": "000660",
                    }
                ],
            }
        ],
    )

    assert violation is not None
    assert violation.failed_layer == "tool_source_validation"
    assert violation.observed_codes == ("000660",)


def test_stale_event_context_for_another_stock_is_blocked_before_agent():
    violation = validate_input_source_stock_context(
        selected_stock_code="005930",
        event_context=[{"stock_code": "000660", "event_id": "news-1"}],
        source_id=None,
    )

    assert violation is not None
    assert violation.failed_layer == "input_source_context"


def test_normal_financial_tool_receives_authoritative_selected_stock(monkeypatch):
    captured = {}

    def fake_run(_facts, inp):
        captured["input"] = inp
        return ok({"facts": []})

    monkeypatch.setattr("app.agent.runtime.run_get_financial_facts", fake_run)
    tool = next(tool for tool in build_tools() if tool.name == "get_financial_facts")
    runtime = _Runtime()
    result = json.loads(
        tool.func(
            stock_code="005930",
            runtime=runtime,
            account_name="영업이익",
        )
    )

    assert result["status"] == "ok"
    assert captured["input"].stock_code == "005930"
    assert runtime.context.stock_context_events == []


@pytest.mark.parametrize(
    "question",
    [
        "이 종목 지금 핵심만 정리해줘",
        "최근 주가가 어떻게 움직였어?",
        "최근 호재만 알려줘. 실적 관련은 제외해.",
        "실제 실적과 증권사 전망을 비교해줘.",
        "발표 전후 주가는 어떻게 움직였어?",
        "관련된 공식 공시가 있어?",
        "이 공시 핵심 숫자만 알려줘",
        "관련 뉴스가 있어?",
        "다른 증권사 의견과 비교해줘",
        "회사 발표 내용만 알려줘",
        "반도체 업황 뉴스 알려줘",
        "가장 최근 공시는 뭐고 그 공시로 인해 주가가 어떻게 되었어",
    ],
)
def test_existing_single_stock_questions_are_not_false_positive_company_mentions(question):
    assert validate_question_stock_context(question, "005930").allowed
