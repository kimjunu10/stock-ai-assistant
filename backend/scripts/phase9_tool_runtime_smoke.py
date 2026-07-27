"""Agent-free Phase 9 read-only Tool runtime smoke test.

Usage:
    cd backend
    set -a; source .env; set +a
    .venv/bin/python scripts/phase9_tool_runtime_smoke.py

The command exits non-zero when any normal read-only Tool call returns error,
when first/repeated calls differ, or when the mixed sequential path fails.
It does not execute the Agent, devset, or holdout.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agent.middleware import sanitize_tool_error  # noqa: E402
from app.agent.tools.disclosures import (  # noqa: E402
    DisclosureValuesInput,
    run_get_disclosure_values,
)
from app.agent.tools.financials import (  # noqa: E402
    FinancialFactsInput,
    run_get_financial_facts,
)
from app.agent.tools.news import SearchNewsInput, run_search_news  # noqa: E402
from app.agent.tools.prices import GetStockPricesInput, run_get_stock_prices  # noqa: E402
from app.agent.tools.reports import (  # noqa: E402
    SearchResearchReportsInput,
    run_search_research_reports,
)
from app.agent.tools.terms import FinancialTermInput, run_lookup_financial_term  # noqa: E402
from app.api.routes.stocks import get_toss_client  # noqa: E402
from app.core.config import Settings  # noqa: E402
from app.db.client import get_supabase_client  # noqa: E402
from app.ml.embeddings import UpstageEmbedder  # noqa: E402
from app.rag.retrieval import HybridRetriever  # noqa: E402
from app.services.facts import FactsService  # noqa: E402
from app.services.research_reports import ResearchReportSearch  # noqa: E402
from app.services.stock_prices import StockPriceService  # noqa: E402


def _summary(result) -> dict:
    return {
        "status": result.status,
        "source_count": len(result.sources),
        "warnings": result.warnings,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    cfg = Settings(agent_enabled=True)
    client = get_supabase_client()
    facts = FactsService(client)
    retriever = HybridRetriever(client, cfg, UpstageEmbedder(cfg))
    reports = ResearchReportSearch(client, cfg, retriever)
    if not cfg.toss_client_id or not cfg.toss_client_secret:
        print("FAIL: Toss credentials are required for the price control Tool.", file=sys.stderr)
        return 2
    prices = StockPriceService(
        get_toss_client(),
        cache_seconds=cfg.stock_price_cache_seconds,
        rate_limit_retries=cfg.stock_price_rate_limit_retries,
        rate_limit_backoff_seconds=cfg.stock_price_rate_limit_backoff_seconds,
        max_candle_pages=cfg.stock_price_max_candle_pages,
    )

    calls = {
        "lookup_financial_term_default": lambda: run_lookup_financial_term(
            facts, FinancialTermInput(term="자기자본이익률")
        ),
        "lookup_financial_term_alternate": lambda: run_lookup_financial_term(
            facts, FinancialTermInput(term="주가수익비율")
        ),
        "get_financial_facts_default": lambda: run_get_financial_facts(
            facts,
            FinancialFactsInput(stock_code="005930", period_mode="latest"),
        ),
        "get_financial_facts_optional": lambda: run_get_financial_facts(
            facts,
            FinancialFactsInput(
                stock_code="005930",
                account_name="매출액",
                business_year=2025,
                report_period="q1",
                amount_type="cumulative",
            ),
        ),
        "search_news_default": lambda: run_search_news(
            retriever,
            SearchNewsInput(stock_code="005930"),
        ),
        "search_news_optional": lambda: run_search_news(
            retriever,
            SearchNewsInput(stock_code="005930", query="반도체"),
        ),
        "get_disclosure_values_default": lambda: run_get_disclosure_values(
            facts,
            DisclosureValuesInput(stock_code="005930"),
        ),
        "get_disclosure_values_optional": lambda: run_get_disclosure_values(
            facts,
            DisclosureValuesInput(stock_code="005930", event_types=["dividend_matter"]),
        ),
        "search_research_reports_default": lambda: run_search_research_reports(
            reports,
            SearchResearchReportsInput(stock_code="005930", query=""),
        ),
        "search_research_reports_optional": lambda: run_search_research_reports(
            reports,
            SearchResearchReportsInput(
                stock_code="005930",
                query="목표주가",
                broker="키움증권",
                time_context="current",
            ),
        ),
        "get_stock_prices_default": lambda: run_get_stock_prices(
            prices, GetStockPricesInput(stock_code="005930")
        ),
        "get_stock_prices_optional": lambda: run_get_stock_prices(
            prices, GetStockPricesInput(stock_code="005930", lookback="1m")
        ),
    }

    rows: list[dict] = []
    failed = False
    for name, call in calls.items():
        statuses = []
        for attempt in (1, 2):
            result = call()
            row = {"tool": name, "attempt": attempt, **_summary(result)}
            rows.append(row)
            statuses.append(result.status)
            failed |= result.status != "ok"
        failed |= statuses[0] != statuses[1]

    sequence = [
        (
            "mixed_financial",
            run_get_financial_facts(
                facts,
                FinancialFactsInput(
                    stock_code="042660",
                    account_names=["매출액", "영업이익", "당기순이익"],
                    period_mode="latest",
                ),
            ),
        ),
        (
            "mixed_news",
            run_search_news(
                retriever,
                SearchNewsInput(stock_code="042660", query="배당 정책"),
            ),
        ),
        (
            "mixed_disclosure",
            run_get_disclosure_values(
                facts,
                DisclosureValuesInput(stock_code="042660", event_types=["dividend_matter"]),
            ),
        ),
    ]
    for name, result in sequence:
        rows.append({"tool": name, "attempt": 1, **_summary(result)})
        failed |= result.status != "ok"

    missing = run_lookup_financial_term(facts, FinancialTermInput(term="__phase9_missing_term__"))
    rows.append({"tool": "missing_term", "attempt": 1, **_summary(missing)})
    failed |= missing.status != "no_data"

    try:
        FinancialFactsInput(
            stock_code="005930",
            account_names=["순이익"],
            period_mode="latest",
        )
        validation_payload = {"status": "unexpected_ok"}
    except ValidationError as exc:
        validation_payload = json.loads(sanitize_tool_error(exc))
    rows.append(
        {
            "tool": "invalid_financial_args",
            "attempt": 1,
            "status": validation_payload.get("status"),
            "source_count": len(validation_payload.get("sources") or []),
            "warnings": validation_payload.get("warnings") or [],
        }
    )
    failed |= validation_payload.get("status") != "error"

    result = {
        "status": "fail" if failed else "pass",
        "executed_at": datetime.now().astimezone().isoformat(),
        "agent_executed": False,
        "rows": rows,
    }
    if args.output:
        args.output.write_text(
            json.dumps(result, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
