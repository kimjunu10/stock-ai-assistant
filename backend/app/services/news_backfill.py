"""Solar call budgets, rate limiting, and cost accounting for news backfills."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any

from app.services.news_clustering import BackfillBudgetExhausted
from experiments.exp_b_factual_summaries import assign_llm, summarize

# Upstage Solar Pro 3 public API pricing, excluding VAT (checked 2026-07-21).
SOLAR_INPUT_USD_PER_MILLION = 0.15
SOLAR_OUTPUT_USD_PER_MILLION = 0.60

# Conservative pre-call reservations. Actual usage returned by Solar replaces these values.
ASSIGN_ESTIMATED_INPUT_TOKENS = 1_500
ASSIGN_ESTIMATED_OUTPUT_TOKENS = 120
SUMMARY_ESTIMATED_INPUT_TOKENS = 16_000
SUMMARY_ESTIMATED_OUTPUT_TOKENS = 1_000


def solar_cost_usd(prompt_tokens: int, completion_tokens: int) -> float:
    return (
        prompt_tokens * SOLAR_INPUT_USD_PER_MILLION
        + completion_tokens * SOLAR_OUTPUT_USD_PER_MILLION
    ) / 1_000_000


@dataclass(slots=True)
class SolarBackfillBudget:
    max_assignment_calls: int
    max_summary_calls: int
    max_run_cost_usd: float
    max_daily_cost_usd: float
    already_spent_today_usd: float = 0.0
    min_interval_seconds: float = 0.25
    assignment_calls: int = 0
    summary_calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0
    _last_call_at: float = 0.0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def _estimated_next_cost(self, call_kind: str) -> float:
        if call_kind == "assignment":
            return solar_cost_usd(
                ASSIGN_ESTIMATED_INPUT_TOKENS,
                ASSIGN_ESTIMATED_OUTPUT_TOKENS,
            )
        return solar_cost_usd(
            SUMMARY_ESTIMATED_INPUT_TOKENS,
            SUMMARY_ESTIMATED_OUTPUT_TOKENS,
        )

    def _reserve(self, call_kind: str) -> None:
        with self._lock:
            if call_kind == "assignment" and self.assignment_calls >= self.max_assignment_calls:
                raise BackfillBudgetExhausted("assignment call limit reached")
            if call_kind == "summary" and self.summary_calls >= self.max_summary_calls:
                raise BackfillBudgetExhausted("summary call limit reached")
            estimated = self._estimated_next_cost(call_kind)
            if self.cost_usd + estimated > self.max_run_cost_usd:
                raise BackfillBudgetExhausted("per-run cost limit reached")
            if self.already_spent_today_usd + self.cost_usd + estimated > self.max_daily_cost_usd:
                raise BackfillBudgetExhausted("daily cost limit reached")

            wait = self.min_interval_seconds - (time.monotonic() - self._last_call_at)
            if wait > 0:
                time.sleep(wait)
            self._last_call_at = time.monotonic()
            if call_kind == "assignment":
                self.assignment_calls += 1
            else:
                self.summary_calls += 1

    def _record(self, call_kind: str, meta: dict[str, Any]) -> None:
        usage = meta.get("usage") or {}
        prompt = int(usage.get("prompt_tokens") or 0)
        completion = int(usage.get("completion_tokens") or 0)
        if prompt == 0 and completion == 0:
            if call_kind == "assignment":
                prompt = ASSIGN_ESTIMATED_INPUT_TOKENS
                completion = ASSIGN_ESTIMATED_OUTPUT_TOKENS
            else:
                prompt = SUMMARY_ESTIMATED_INPUT_TOKENS
                completion = SUMMARY_ESTIMATED_OUTPUT_TOKENS
        with self._lock:
            self.prompt_tokens += prompt
            self.completion_tokens += completion
            self.cost_usd += solar_cost_usd(prompt, completion)

    def call_assignment(self, api_key: str, prompt: str) -> tuple[dict, dict]:
        self._reserve("assignment")
        try:
            parsed, meta = assign_llm.call_solar_assign(api_key, prompt)
        except Exception:
            self._record("assignment", {})
            raise
        self._record("assignment", meta)
        return parsed, meta

    def call_summary(self, api_key: str, prompt: str) -> tuple[dict, dict]:
        self._reserve("summary")
        try:
            parsed, meta = summarize.call_solar(api_key, prompt)
        except Exception:
            self._record("summary", {})
            raise
        self._record("summary", meta)
        return parsed, meta

    def snapshot(self) -> dict[str, int | float]:
        with self._lock:
            return {
                "assignment_calls": self.assignment_calls,
                "summary_calls": self.summary_calls,
                "prompt_tokens": self.prompt_tokens,
                "completion_tokens": self.completion_tokens,
                "cost_usd": round(self.cost_usd, 6),
            }
