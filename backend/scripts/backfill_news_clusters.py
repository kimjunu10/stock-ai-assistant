"""Inventory and safely backfill relevant news-cluster assignment pairs."""

from __future__ import annotations

import argparse
import json
import logging
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import numpy as np

from app.core.config import settings
from app.db.client import get_supabase_client
from app.repositories.news_clusters import NewsClusterRepository
from app.services.news_backfill import (
    ASSIGN_ESTIMATED_INPUT_TOKENS,
    ASSIGN_ESTIMATED_OUTPUT_TOKENS,
    SUMMARY_ESTIMATED_INPUT_TOKENS,
    SUMMARY_ESTIMATED_OUTPUT_TOKENS,
    SolarBackfillBudget,
    solar_cost_usd,
)
from app.services.news_clustering import BgeM3Embedder, NewsClusteringService
from experiments.exp_b_factual_summaries import config as cluster_cfg
from experiments.exp_b_factual_summaries.market_rules import classify_kind

logger = logging.getLogger("news_cluster_backfill")
PAGE_SIZE = 1000


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", action="store_true", help="Read-only DB inventory")
    parser.add_argument(
        "--estimate-calls",
        action="store_true",
        help="Read-only BGE simulation of company candidate/Solar call volume",
    )
    parser.add_argument("--execute", action="store_true", help="Allow DB writes and Solar calls")
    parser.add_argument("--batch-size", type=int, default=settings.news_backfill_batch_size)
    parser.add_argument("--pilot-company-candidates", type=int, default=0)
    parser.add_argument("--pilot-scan-pairs", type=int, default=500)
    parser.add_argument(
        "--max-assignment-calls", type=int, default=settings.news_backfill_max_assignment_calls
    )
    parser.add_argument(
        "--max-summary-calls", type=int, default=settings.news_backfill_max_summary_calls
    )
    parser.add_argument("--max-cost-usd", type=float, default=settings.news_backfill_max_cost_usd)
    parser.add_argument(
        "--daily-cost-usd", type=float, default=settings.news_backfill_daily_cost_usd
    )
    parser.add_argument("--run-key", default="relevant-news-v1")
    parser.add_argument("--log-every-pairs", type=int, default=10)
    parser.add_argument("--all", action="store_true", help="Select every currently unassigned pair")
    parser.add_argument("--approve-full-backfill", action="store_true")
    return parser.parse_args()


def _paged(fetch: Callable[[int, int], Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    offset = 0
    while True:
        page = list(fetch(offset, offset + PAGE_SIZE - 1).data or [])
        rows.extend(page)
        if len(page) < PAGE_SIZE:
            return rows
        offset += PAGE_SIZE


def collect_inventory(client: Any, *, include_rows: bool = False) -> dict[str, Any]:
    all_articles = (
        client.table("articles").select("id", count="exact").limit(1).execute().count or 0
    )
    crawled_success = (
        client.table("articles")
        .select("id", count="exact")
        .eq("crawl_status", "success")
        .limit(1)
        .execute()
        .count
        or 0
    )
    relevant_links = _paged(
        lambda start, end: (
            client.table("article_stocks")
            .select("article_id,stock_code")
            .eq("relevance", "relevant")
            .order("article_id")
            .order("stock_code")
            .range(start, end)
            .execute()
        )
    )
    eligible_links = _paged(
        lambda start, end: (
            client.table("article_stocks")
            .select(
                "article_id,stock_code,articles!inner("
                "id,title,description,body,press,published_at,crawl_status)"
            )
            .eq("relevance", "relevant")
            .eq("articles.crawl_status", "success")
            .order("published_at", foreign_table="articles")
            .order("article_id")
            .order("stock_code")
            .range(start, end)
            .execute()
        )
    )
    assigned_links = _paged(
        lambda start, end: (
            client.table("news_cluster_assignments")
            .select("article_id,stock_code")
            .in_("status", ["assigned_new", "assigned_existing"])
            .order("article_id")
            .order("stock_code")
            .range(start, end)
            .execute()
        )
    )
    assigned_pairs = {(int(row["article_id"]), row["stock_code"]) for row in assigned_links}
    unassigned = [
        row
        for row in eligible_links
        if (int(row["article_id"]), row["stock_code"]) not in assigned_pairs
    ]

    kind_pairs = {"company": 0, "market": 0, "info": 0}
    kind_articles: dict[str, set[int]] = {"company": set(), "market": set(), "info": set()}
    normalized_rows: list[dict[str, Any]] = []
    for link in unassigned:
        article = link.get("articles") or {}
        kind = classify_kind(article.get("title") or "", article.get("description") or "")
        article_id = int(link["article_id"])
        kind_pairs[kind] += 1
        kind_articles[kind].add(article_id)
        if include_rows:
            normalized_rows.append(
                {
                    **article,
                    "article_id": article_id,
                    "stock_code": link["stock_code"],
                    "kind": kind,
                }
            )

    summary_retry_count = (
        client.table("news_clusters")
        .select("id", count="exact")
        .in_("summary_status", ["pending", "pending_retry"])
        .limit(1)
        .execute()
        .count
        or 0
    )
    assignment_upper = kind_pairs["company"]
    summary_upper = len(unassigned) + summary_retry_count
    conservative_cost = solar_cost_usd(
        assignment_upper * ASSIGN_ESTIMATED_INPUT_TOKENS
        + summary_upper * SUMMARY_ESTIMATED_INPUT_TOKENS,
        assignment_upper * ASSIGN_ESTIMATED_OUTPUT_TOKENS
        + summary_upper * SUMMARY_ESTIMATED_OUTPUT_TOKENS,
    )
    result = {
        "all_articles": all_articles,
        "crawled_success_articles": crawled_success,
        "relevant_distinct_articles": len({int(row["article_id"]) for row in relevant_links}),
        "relevant_pairs": len(relevant_links),
        "eligible_relevant_distinct_articles": len(
            {int(row["article_id"]) for row in eligible_links}
        ),
        "eligible_relevant_pairs": len(eligible_links),
        "unassigned_distinct_articles": len({int(row["article_id"]) for row in unassigned}),
        "unassigned_pairs": len(unassigned),
        "expected_kind_pairs": kind_pairs,
        "expected_kind_distinct_articles": {
            kind: len(article_ids) for kind, article_ids in kind_articles.items()
        },
        "assignment_calls_upper_bound": assignment_upper,
        "summary_calls_upper_bound": summary_upper,
        "summary_retry_clusters": summary_retry_count,
        "conservative_cost_usd_ex_vat": round(conservative_cost, 4),
    }
    if include_rows:
        result["unassigned_rows"] = normalized_rows
    return result


def find_company_candidate_pilots(
    repo: NewsClusterRepository,
    inventory_rows: list[dict[str, Any]],
    *,
    count: int,
    scan_pairs: int,
) -> list[dict[str, Any]]:
    embedder = BgeM3Embedder(settings.news_embedding_device)
    found: list[dict[str, Any]] = []
    company_rows = sorted(
        (row for row in inventory_rows if row["kind"] == "company"),
        key=lambda row: (row.get("published_at") or "", row["article_id"], row["stock_code"]),
        reverse=True,
    )
    scanned = 0
    for row in company_rows:
        if scanned >= scan_pairs or len(found) >= count:
            break
        scanned += 1
        active = repo.get_active_clusters(
            row["stock_code"],
            "company",
            row["published_at"],
            cluster_cfg.ACTIVE_WINDOW_HOURS,
        )
        if not active:
            continue
        vector = embedder.encode(row)
        similarities = [
            float(np.dot(vector, np.asarray(cluster["centroid"], dtype=np.float32)))
            for cluster in active
        ]
        if not similarities or max(similarities) < cluster_cfg.LLM_ASSIGN_CANDIDATE_MIN_SIM:
            continue
        found.append(
            {
                **row,
                "stock_codes": [row["stock_code"]],
                "pair_count": 1,
                "retry_count": 0,
                "pilot_max_similarity": round(max(similarities), 6),
            }
        )
    logger.info(
        "PILOT_SCAN scanned_pairs=%d candidate_pairs=%d requested=%d",
        scanned,
        len(found),
        count,
    )
    return found


def estimate_company_assignment_calls(
    inventory_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    """Estimate candidate-triggered Solar calls without Solar or DB writes.

    The distance-only 0.74 merge threshold is used solely to advance simulated
    centroids. Production assignment continues to use Solar whenever a >=0.55
    candidate exists.
    """

    started = time.monotonic()
    company_rows = sorted(
        (row for row in inventory_rows if row["kind"] == "company"),
        key=lambda row: (row.get("published_at") or "", row["article_id"], row["stock_code"]),
    )
    unique_articles: dict[int, dict[str, Any]] = {}
    for row in company_rows:
        unique_articles.setdefault(int(row["article_id"]), row)
    article_ids = list(unique_articles)
    embedder = BgeM3Embedder(settings.news_embedding_device)
    encoded = embedder.encode_many([unique_articles[article_id] for article_id in article_ids])
    vectors = {article_id: encoded[index] for index, article_id in enumerate(article_ids)}

    # Each tuple is [centroid, article_count, last_active_hours]. This is a
    # planning-only approximation; it never becomes production cluster state.
    clusters: dict[str, list[list[Any]]] = {}
    candidate_calls = 0
    no_candidate_pairs = 0
    proxy_existing = 0
    proxy_new = 0
    for row in company_rows:
        vector = vectors[int(row["article_id"])]
        published_hours = (
            datetime.fromisoformat(row["published_at"].replace("Z", "+00:00")).timestamp() / 3600.0
        )
        active = [
            cluster
            for cluster in clusters.get(row["stock_code"], [])
            if published_hours - float(cluster[2]) <= cluster_cfg.ACTIVE_WINDOW_HOURS
        ]
        candidates = [
            (float(np.dot(vector, np.asarray(cluster[0], dtype=np.float32))), cluster)
            for cluster in active
        ]
        candidates = [
            item for item in candidates if item[0] >= cluster_cfg.LLM_ASSIGN_CANDIDATE_MIN_SIM
        ]
        candidates.sort(key=lambda item: item[0], reverse=True)
        if candidates:
            candidate_calls += 1
        else:
            no_candidate_pairs += 1

        # Proxy only: the old distance threshold gives the simulation a stable
        # way to update centroids while Solar remains the production authority.
        if candidates and candidates[0][0] >= cluster_cfg.COSINE_THRESHOLD:
            cluster = candidates[0][1]
            count = int(cluster[1])
            centroid = (np.asarray(cluster[0]) * count + vector) / (count + 1)
            norm = float(np.linalg.norm(centroid))
            cluster[0] = centroid / norm if norm else centroid
            cluster[1] = count + 1
            cluster[2] = published_hours
            proxy_existing += 1
        else:
            clusters.setdefault(row["stock_code"], []).append([vector.copy(), 1, published_hours])
            proxy_new += 1

    return {
        "company_pairs": len(company_rows),
        "company_distinct_articles": len(unique_articles),
        "estimated_assignment_calls": candidate_calls,
        "no_candidate_pairs": no_candidate_pairs,
        "candidate_rate": round(candidate_calls / max(1, len(company_rows)), 6),
        "proxy_existing": proxy_existing,
        "proxy_new": proxy_new,
        "method": (
            f"bge_m3_{cluster_cfg.ACTIVE_WINDOW_HOURS}h_candidate_simulation_proxy_merge_at_0.74"
        ),
        "elapsed_seconds": round(time.monotonic() - started, 3),
    }


def _add_usage(base: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
    return {
        key: float(base.get(key) or 0) + float(current.get(key) or 0)
        for key in (
            "assignment_calls",
            "summary_calls",
            "prompt_tokens",
            "completion_tokens",
            "cost_usd",
        )
    }


def main() -> int:
    args = parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        force=True,
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    client = get_supabase_client()
    inventory = collect_inventory(
        client,
        include_rows=args.pilot_company_candidates > 0 or args.estimate_calls,
    )
    printable_inventory = {
        key: value for key, value in inventory.items() if key != "unassigned_rows"
    }
    print(
        "BACKFILL_INVENTORY=" + json.dumps(printable_inventory, ensure_ascii=False, sort_keys=True)
    )
    if args.estimate_calls:
        estimate = estimate_company_assignment_calls(list(inventory.get("unassigned_rows") or []))
        print("BACKFILL_CALL_ESTIMATE=" + json.dumps(estimate, ensure_ascii=False, sort_keys=True))
    if (args.inventory or args.estimate_calls) and not args.execute:
        return 0
    if not args.execute:
        raise SystemExit("DB writes require --execute")
    if not settings.use_llm_assign:
        raise SystemExit("USE_LLM_ASSIGN must be true for this backfill")
    if args.all and not args.approve_full_backfill:
        raise SystemExit("--all requires explicit --approve-full-backfill")

    repo = NewsClusterRepository(client, settings)
    previous = repo.get_backfill_run(args.run_key) or {}
    previous_usage = {
        "assignment_calls": previous.get("assignment_calls") or 0,
        "summary_calls": previous.get("summary_calls") or 0,
        "prompt_tokens": previous.get("prompt_tokens") or 0,
        "completion_tokens": previous.get("completion_tokens") or 0,
        "cost_usd": previous.get("estimated_cost_usd") or 0,
    }
    spent_today = repo.get_today_backfill_cost()
    budget = SolarBackfillBudget(
        max_assignment_calls=args.max_assignment_calls,
        max_summary_calls=args.max_summary_calls,
        max_run_cost_usd=args.max_cost_usd,
        max_daily_cost_usd=args.daily_cost_usd,
        already_spent_today_usd=spent_today,
        min_interval_seconds=settings.news_backfill_solar_min_interval_seconds,
    )
    limits = {
        "batch_size_pairs": args.batch_size,
        "max_assignment_calls": args.max_assignment_calls,
        "max_summary_calls": args.max_summary_calls,
        "max_run_cost_usd": args.max_cost_usd,
        "max_daily_cost_usd": args.daily_cost_usd,
    }
    repo.start_backfill_run(args.run_key, limits)
    latest_totals: dict[str, Any] = {}

    def progress(article: dict[str, Any], outcome: str, totals: dict[str, int]) -> None:
        nonlocal latest_totals
        latest_totals = dict(totals)
        combined_usage = _add_usage(previous_usage, budget.snapshot())
        checkpoint_article = article if outcome in {"completed", "duplicate"} else None
        repo.update_backfill_run(
            args.run_key,
            status="running",
            totals=latest_totals,
            usage=combined_usage,
            article=checkpoint_article,
        )
        if totals["pairs_scanned"] % max(1, args.log_every_pairs) == 0:
            logger.info(
                "BACKFILL_PROGRESS pairs=%d completed=%d pending_retry=%d "
                "assigned_new=%d assigned_existing=%d assignment_calls=%d "
                "summary_calls=%d cost_usd=%.6f",
                totals["pairs_scanned"],
                totals["completed"],
                totals["pending_retry"],
                totals["assigned_new"],
                totals["assigned_existing"],
                budget.assignment_calls,
                budget.summary_calls,
                budget.cost_usd,
            )

    service = NewsClusteringService(
        repo,
        settings,
        assign_call_fn=lambda prompt: budget.call_assignment(settings.upstage_api_key, prompt),
        summary_call_fn=lambda prompt: budget.call_summary(settings.upstage_api_key, prompt),
        progress_fn=progress,
    )
    try:
        if args.pilot_company_candidates:
            candidates = find_company_candidate_pilots(
                repo,
                list(inventory.get("unassigned_rows") or []),
                count=args.pilot_company_candidates,
                scan_pairs=args.pilot_scan_pairs,
            )
            if len(candidates) < args.pilot_company_candidates:
                raise RuntimeError("Not enough unassigned company pairs with real candidates")
            totals = service.process_pending(
                len(candidates),
                candidates=candidates,
                retry_summaries=False,
            )
        else:
            pair_limit = inventory["unassigned_pairs"] if args.all else args.batch_size
            totals = service.process_pending(pair_limit)
        latest_totals = totals
        status = "stopped_budget" if totals["stopped_budget"] else "completed"
        combined_usage = _add_usage(previous_usage, budget.snapshot())
        repo.update_backfill_run(
            args.run_key,
            status=status,
            totals=totals,
            usage=combined_usage,
        )
    except KeyboardInterrupt:
        repo.update_backfill_run(
            args.run_key,
            status="stopped",
            totals=latest_totals,
            usage=_add_usage(previous_usage, budget.snapshot()),
            last_error="KeyboardInterrupt",
        )
        raise
    except Exception as exc:
        repo.update_backfill_run(
            args.run_key,
            status="failed",
            totals=latest_totals,
            usage=_add_usage(previous_usage, budget.snapshot()),
            last_error=f"{type(exc).__name__}: {exc}",
        )
        raise

    result = {
        "run_key": args.run_key,
        "finished_at": datetime.now(UTC).isoformat(),
        "totals": totals,
        "usage_this_execution": budget.snapshot(),
        "status": status,
    }
    print("BACKFILL_RESULT=" + json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
