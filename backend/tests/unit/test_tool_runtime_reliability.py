"""Phase 9 Tool runtime error contract and internal observability regression tests."""

from __future__ import annotations

import json
import logging

import pytest
from pydantic import ValidationError

from app.agent.middleware import (
    ToolRuntimeObservabilityMiddleware,
    sanitize_tool_error,
)
from app.agent.tools.common import (
    log_tool_exception,
    mask_tool_args,
    tool_runtime_log_context,
)
from app.agent.tools.financials import FinancialFactsInput
from app.agent.tools.terms import FinancialTermInput, run_lookup_financial_term
from app.eval.recorder import _status_of


def test_mask_tool_args_masks_nested_secrets() -> None:
    masked = mask_tool_args(
        {
            "stock_code": "005930",
            "api_key": "top-secret",
            "nested": {"authorization": "Bearer secret", "query": "반도체"},
        }
    )

    assert masked == {
        "stock_code": "005930",
        "api_key": "***",
        "nested": {"authorization": "***", "query": "반도체"},
    }


def test_internal_exception_log_has_required_fields_and_masks_secrets(caplog) -> None:
    try:
        raise RuntimeError(
            "token=private-token postgresql://dbuser:private-password@db.local refused"
        )
    except RuntimeError as exc:
        with tool_runtime_log_context(
            tool_name="search_news",
            args={"stock_code": "005930", "password": "private-password"},
            request_id="req-123",
        ):
            with caplog.at_level(logging.ERROR, logger="app.agent.tools.common"):
                log_tool_exception(exc, layer="HybridRetriever.search_news")

    message = caplog.messages[-1]
    assert "tool=search_news" in message
    assert '"stock_code": "005930"' in message
    assert '"password": "***"' in message
    assert "exception_class=RuntimeError" in message
    assert "exception_message=token=*** postgresql://dbuser:***@db.local refused" in message
    assert "layer=HybridRetriever.search_news" in message
    assert "correlation_id=req-123" in message
    assert "stack_trace=" in message
    assert "private-token" not in message
    assert "private-password" not in message


def test_validation_error_becomes_standard_error_status() -> None:
    with pytest.raises(ValidationError) as caught:
        FinancialFactsInput(
            stock_code="005930",
            account_names=["순이익"],
            period_mode="latest",
        )

    content = sanitize_tool_error(caught.value)
    payload = json.loads(content)

    assert payload["status"] == "error"
    assert payload["data"] == {}
    assert payload["sources"] == []
    assert any("입력값" in warning for warning in payload["warnings"])
    assert _status_of(content) == "error"


class _BrokenFacts:
    def lookup_term(self, _term):
        raise ConnectionError("password=db-secret connection reset")


def test_caught_service_exception_is_logged_but_public_result_is_sanitized(caplog) -> None:
    with tool_runtime_log_context(
        tool_name="lookup_financial_term",
        args={"term": "PER"},
        request_id="req-term",
    ):
        with caplog.at_level(logging.ERROR, logger="app.agent.tools.common"):
            result = run_lookup_financial_term(
                _BrokenFacts(),
                FinancialTermInput(term="PER"),
            )

    assert result.status == "error"
    assert "db-secret" not in json.dumps(result.model_dump_agent(), ensure_ascii=False)
    message = caplog.messages[-1]
    assert "exception_class=ConnectionError" in message
    assert "exception_message=password=*** connection reset" in message
    assert "layer=FactsService.lookup_term" in message
    assert "correlation_id=req-term" in message


class _Context:
    request_id = "req-observe"


class _Runtime:
    context = _Context()


class _Request:
    tool_name = "get_financial_facts"
    tool_call = {
        "name": "get_financial_facts",
        "args": {"stock_code": "005930", "credential": "hidden"},
        "id": "call-1",
    }
    runtime = _Runtime()


def test_observability_middleware_propagates_request_context(caplog) -> None:
    middleware = ToolRuntimeObservabilityMiddleware()

    def handler(_request):
        try:
            raise OSError("temporary failure")
        except OSError as exc:
            log_tool_exception(exc, layer="FactsService.get_financials")
        return "handled"

    with caplog.at_level(logging.ERROR, logger="app.agent.tools.common"):
        assert middleware.wrap_tool_call(_Request(), handler) == "handled"

    message = caplog.messages[-1]
    assert "tool=get_financial_facts" in message
    assert '"credential": "***"' in message
    assert "correlation_id=req-observe" in message
