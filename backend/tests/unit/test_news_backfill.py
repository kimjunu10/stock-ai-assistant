from __future__ import annotations

import pytest

from app.services import news_backfill
from app.services.news_backfill import SolarBackfillBudget, solar_cost_usd
from app.services.news_clustering import BackfillBudgetExhausted


def test_solar_budget_records_actual_usage_and_stops_before_second_call(monkeypatch) -> None:
    monkeypatch.setattr(
        news_backfill.assign_llm,
        "call_solar_assign",
        lambda _key, _prompt: (
            {"decision": "new", "matched_cluster_id": None},
            {
                "ok": True,
                "parse_success": True,
                "usage": {"prompt_tokens": 1000, "completion_tokens": 100},
            },
        ),
    )
    budget = SolarBackfillBudget(
        max_assignment_calls=1,
        max_summary_calls=1,
        max_run_cost_usd=1.0,
        max_daily_cost_usd=2.0,
        min_interval_seconds=0,
    )

    budget.call_assignment("test", "prompt")

    assert budget.assignment_calls == 1
    assert budget.cost_usd == solar_cost_usd(1000, 100)
    with pytest.raises(BackfillBudgetExhausted, match="assignment call limit"):
        budget.call_assignment("test", "prompt")


def test_solar_budget_enforces_daily_cost_before_call() -> None:
    budget = SolarBackfillBudget(
        max_assignment_calls=10,
        max_summary_calls=10,
        max_run_cost_usd=1.0,
        max_daily_cost_usd=0.001,
        already_spent_today_usd=0.001,
        min_interval_seconds=0,
    )

    with pytest.raises(BackfillBudgetExhausted, match="daily cost limit"):
        budget.call_summary("test", "prompt")


def test_solar_budget_accounts_conservative_usage_when_transport_raises(monkeypatch) -> None:
    def fail(_key: str, _prompt: str):
        raise RuntimeError("network disconnected")

    monkeypatch.setattr(news_backfill.summarize, "call_solar", fail)
    budget = SolarBackfillBudget(
        max_assignment_calls=1,
        max_summary_calls=1,
        max_run_cost_usd=1.0,
        max_daily_cost_usd=2.0,
        min_interval_seconds=0,
    )

    with pytest.raises(RuntimeError, match="network disconnected"):
        budget.call_summary("test", "prompt")

    assert budget.summary_calls == 1
    assert budget.cost_usd == solar_cost_usd(
        news_backfill.SUMMARY_ESTIMATED_INPUT_TOKENS,
        news_backfill.SUMMARY_ESTIMATED_OUTPUT_TOKENS,
    )
