"""뉴스 상대 기간은 사용자 표현으로만 결정되는지 검증한다."""

from __future__ import annotations

import json
from datetime import date

import pytest

from app.agent.context import ToolServices
from app.agent.runtime import build_tools
from app.agent.time_context import (
    effective_news_relative_period,
    explicit_relative_period,
    resolve_relative_date_range,
)
from app.agent.tools.common import ok


@pytest.mark.parametrize(
    "question",
    [
        "오로라 신제품 공개 건은 어떤 내용이야?",
        "A사 공급계약 뉴스 설명해줘",
        "김대표 기자간담회 건 설명해줘",
    ],
)
def test_event_question_without_time_has_no_relative_period(question):
    assert explicit_relative_period(question) is None
    assert effective_news_relative_period(question, "recent") is None


def test_recent_news_uses_recent():
    assert explicit_relative_period("최근 뉴스 알려줘") == "recent"
    assert effective_news_relative_period("요즘 무슨 일 있어?", None) == "recent"


def test_last_month_uses_previous_calendar_month():
    assert explicit_relative_period("지난달 뉴스 알려줘") == "last_month"
    assert resolve_relative_date_range("last_month", reference_date=date(2026, 7, 27)) == (
        "2026-06-01",
        "2026-06-30",
    )


@pytest.mark.parametrize(
    ("question", "period"),
    [
        ("오늘 뉴스 알려줘", "today"),
        ("어제 호재 있었어?", "yesterday"),
        ("이번 주 뉴스", "this_week"),
        ("최근 7일 뉴스", "last_7_days"),
        ("최근 한 달 뉴스", "last_30_days"),
    ],
)
def test_explicit_period_is_preserved(question, period):
    assert explicit_relative_period(question) == period
    assert effective_news_relative_period(question, None) == period


def test_direct_tool_contract_preserves_requested_period_without_question_context():
    assert effective_news_relative_period(None, "recent") == "recent"


class _Runtime:
    def __init__(self, question: str):
        self.context = type(
            "Context",
            (),
            {
                "services": ToolServices(
                    facts=None,
                    retriever=object(),
                    reports=None,
                ),
                "stock_code": "005930",
                "user_question": question,
                "current_date": "2026-07-27",
                "event_status": "none",
            },
        )()


def _search_news_tool():
    return next(tool for tool in build_tools() if tool.name == "search_news")


def test_tool_passes_stock_query_and_drops_unstated_recent(monkeypatch):
    captured = {}

    def fake_run(_retriever, inp):
        captured["input"] = inp
        return ok({"news": []})

    monkeypatch.setattr("app.agent.runtime.run_search_news", fake_run)
    payload = json.loads(
        _search_news_tool().func(
            stock_code="005930",
            runtime=_Runtime("오로라 공급계약 건 설명해줘"),
            query="오로라 공급계약",
            relative_period="recent",
        )
    )

    inp = captured["input"]
    assert payload["status"] == "ok"
    assert inp.stock_code == "005930"
    assert inp.query == "오로라 공급계약"
    assert inp.date_from is None
    assert inp.date_to is None


def test_tool_applies_explicit_recent_when_model_omits_it(monkeypatch):
    captured = {}

    def fake_run(_retriever, inp):
        captured["input"] = inp
        return ok({"news": []})

    monkeypatch.setattr("app.agent.runtime.run_search_news", fake_run)
    json.loads(
        _search_news_tool().func(
            stock_code="005930",
            runtime=_Runtime("최근 뉴스 알려줘"),
            query=None,
            relative_period=None,
        )
    )

    inp = captured["input"]
    assert inp.date_from == "2026-07-25"
    assert inp.date_to == "2026-07-27"


def test_tool_forces_negative_news_for_price_drop_question(monkeypatch):
    captured = {}

    def fake_run(_retriever, inp):
        captured["input"] = inp
        return ok({"news": []})

    monkeypatch.setattr("app.agent.runtime.run_search_news", fake_run)
    json.loads(
        _search_news_tool().func(
            stock_code="005930",
            runtime=_Runtime("어제 주가가 왜 떨어졌지? 무슨 일 있었어?"),
            query=None,
            sentiment=None,
            relative_period=None,
            purpose="price_driver_down",
        )
    )

    inp = captured["input"]
    assert inp.sentiment == "negative"
    assert inp.purpose == "price_driver_down"
    assert inp.date_from == "2026-07-26"
    assert inp.date_to == "2026-07-26"


def test_tool_applies_explicit_last_month_without_changing_query(monkeypatch):
    captured = {}

    def fake_run(_retriever, inp):
        captured["input"] = inp
        return ok({"news": []})

    monkeypatch.setattr("app.agent.runtime.run_search_news", fake_run)
    json.loads(
        _search_news_tool().func(
            stock_code="005930",
            runtime=_Runtime("지난달 배당 정책 관련 뉴스 알려줘"),
            query="배당 정책",
            relative_period="recent",
        )
    )

    inp = captured["input"]
    assert inp.stock_code == "005930"
    assert inp.query == "배당 정책"
    assert inp.date_from == "2026-06-01"
    assert inp.date_to == "2026-06-30"


def test_event_return_only_question_does_not_fetch_unrelated_recent_news(monkeypatch):
    called = False

    def fake_run(_retriever, _inp):
        nonlocal called
        called = True
        return ok({"news": []})

    monkeypatch.setattr("app.agent.runtime.run_search_news", fake_run)
    runtime = _Runtime("유상증자 공시 뜨고 주가 어떻게 됐어?")
    runtime.context.event_status = "resolved"
    payload = json.loads(
        _search_news_tool().func(
            stock_code="005930",
            runtime=runtime,
            query=None,
        )
    )

    assert payload["status"] == "no_data"
    assert called is False
