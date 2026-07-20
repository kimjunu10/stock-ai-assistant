"""Two-phase, resumable full news backfill with deferred cluster summaries."""

from __future__ import annotations

import argparse
import json
import logging
import threading
import time
from collections import defaultdict
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from typing import Any

from app.core.config import settings
from app.db.client import create_supabase_client, get_supabase_client
from app.repositories.news_clusters import NewsClusterRepository
from app.services.news_backfill import SolarBackfillBudget
from app.services.news_clustering import (
    STOCK_NAMES,
    BackfillBudgetExhausted,
    BgeM3Embedder,
    NewsClusteringService,
)
from experiments.exp_b_factual_summaries import config as cluster_cfg
from experiments.exp_b_factual_summaries import summarize
from scripts.backfill_news_clusters import collect_inventory, find_company_candidate_pilots

logger = logging.getLogger("full_news_backfill")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-key", default="full-news-backfill-v2-20260721")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--preflight-pairs", type=int, default=25)
    parser.add_argument("--preflight-scan-pairs", type=int, default=1500)
    parser.add_argument("--log-every", type=int, default=25)
    parser.add_argument("--execute", action="store_true")
    return parser.parse_args()


class AdaptiveSolarGate:
    """Limit concurrent Solar calls and stop on sustained API failures."""

    def __init__(self, workers: int):
        self.max_limit = workers
        self.limit = workers
        self.active = 0
        self.total = 0
        self.failures = 0
        self.consecutive_failures = 0
        self.consecutive_successes = 0
        self.halt_reason: str | None = None
        self._condition = threading.Condition()

    def ensure_running(self) -> None:
        with self._condition:
            if self.halt_reason:
                raise BackfillBudgetExhausted(self.halt_reason)

    def call(self, fn: Callable[[], tuple[dict, dict]]) -> tuple[dict, dict]:
        with self._condition:
            while self.active >= self.limit and not self.halt_reason:
                self._condition.wait()
            if self.halt_reason:
                raise BackfillBudgetExhausted(self.halt_reason)
            self.active += 1
        parsed: dict = {}
        meta: dict = {}
        raised: Exception | None = None
        try:
            parsed, meta = fn()
            return parsed, meta
        except Exception as exc:  # caller persists the affected pair/cluster
            raised = exc
            raise
        finally:
            success = raised is None and bool(meta.get("ok")) and bool(meta.get("parse_success"))
            with self._condition:
                self.active -= 1
                self.total += 1
                if success:
                    self.consecutive_failures = 0
                    self.consecutive_successes += 1
                    if self.consecutive_successes >= 50 and self.limit < self.max_limit:
                        self.limit += 1
                        self.consecutive_successes = 0
                        logger.info("SOLAR_WORKERS_RECOVERED limit=%d", self.limit)
                else:
                    self.failures += 1
                    self.consecutive_failures += 1
                    self.consecutive_successes = 0
                    self.limit = max(1, self.limit - 1)
                    logger.warning(
                        "SOLAR_WORKERS_REDUCED limit=%d failures=%d total=%d",
                        self.limit,
                        self.failures,
                        self.total,
                    )
                if self.consecutive_failures >= 20:
                    self.halt_reason = "20 consecutive Solar failures"
                elif self.total >= 20 and self.failures / self.total > 0.10:
                    self.halt_reason = "Solar error rate exceeded 10%"
                self._condition.notify_all()

    def snapshot(self) -> dict[str, Any]:
        with self._condition:
            return {
                "worker_limit": self.limit,
                "solar_calls": self.total,
                "solar_failures": self.failures,
                "consecutive_failures": self.consecutive_failures,
                "consecutive_successes": self.consecutive_successes,
                "halt_reason": self.halt_reason,
            }


class SharedTotals:
    def __init__(self, initial: dict[str, int] | None = None):
        self.values = defaultdict(int, initial or {})
        self.lock = threading.Lock()

    def add(self, result: dict[str, int]) -> dict[str, int]:
        with self.lock:
            for key, value in result.items():
                self.values[key] += int(value)
            return dict(self.values)

    def snapshot(self) -> dict[str, int]:
        with self.lock:
            return dict(self.values)


def flatten_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    pairs = []
    for article in candidates:
        for stock_code in article["stock_codes"]:
            pairs.append(
                {
                    **article,
                    "stock_code": stock_code,
                    "stock_codes": [stock_code],
                    "pair_count": 1,
                }
            )
    return pairs


def combined_usage(*budgets: SolarBackfillBudget) -> dict[str, Any]:
    result = {
        "assignment_calls": 0,
        "summary_calls": 0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "cost_usd": 0.0,
    }
    for budget in budgets:
        snapshot = budget.snapshot()
        for key in result:
            result[key] += snapshot[key]
    result["cost_usd"] = round(result["cost_usd"], 6)
    return result


def add_usage(base: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key in (
        "assignment_calls",
        "summary_calls",
        "prompt_tokens",
        "completion_tokens",
        "cost_usd",
    ):
        result[key] = float(base.get(key) or 0) + float(current.get(key) or 0)
    for key in ("assignment_calls", "summary_calls", "prompt_tokens", "completion_tokens"):
        result[key] = int(result[key])
    result["cost_usd"] = round(result["cost_usd"], 6)
    return result


def run_assignment_phase(
    rows: list[dict[str, Any]],
    *,
    run_key: str,
    workers: int,
    budget: SolarBackfillBudget,
    gate: AdaptiveSolarGate,
    embedder: BgeM3Embedder,
    log_every: int,
    usage_base: dict[str, Any] | None = None,
) -> dict[str, int]:
    by_stock: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_stock[row["stock_code"]].append(row)
    for stock_rows in by_stock.values():
        stock_rows.sort(key=lambda row: (row.get("published_at") or "", int(row["article_id"])))
    totals = SharedTotals()

    def process_stock(stock_rows: list[dict[str, Any]]) -> None:
        repo = NewsClusterRepository(create_supabase_client(), settings)
        repo.enable_cluster_cache(stock_rows[0]["stock_code"])
        service = NewsClusteringService(
            repo,
            settings,
            embedder=embedder,
            assign_call_fn=lambda prompt: gate.call(
                lambda: budget.call_assignment(settings.upstage_api_key, prompt)
            ),
            summary_call_fn=lambda _prompt: (_ for _ in ()).throw(
                AssertionError("summary must be deferred during assignment phase")
            ),
            defer_summaries=True,
            dirty_run_key=run_key,
            manage_article_state=False,
        )
        for row in stock_rows:
            gate.ensure_running()
            article_id = int(row["article_id"])
            stock_code = row["stock_code"]
            previous = repo.get_assignment(article_id, stock_code)
            if previous and previous["status"] in {"assigned_new", "assigned_existing"}:
                continue
            if not repo.claim_backfill_pair(run_key, article_id, stock_code):
                continue
            try:
                result = service.process_pending(
                    1,
                    candidates=[row],
                    retry_summaries=False,
                )
                if result["pending_retry"]:
                    repo.finish_backfill_pair(
                        run_key,
                        article_id,
                        stock_code,
                        status="pending_retry",
                        error="assignment pending_retry",
                    )
                elif result["stopped_budget"]:
                    repo.finish_backfill_pair(
                        run_key,
                        article_id,
                        stock_code,
                        status="pending_retry",
                        error=gate.halt_reason or "logical call limit reached",
                    )
                    raise BackfillBudgetExhausted(gate.halt_reason or "assignment stopped")
                else:
                    repo.finish_backfill_pair(run_key, article_id, stock_code, status="completed")
            except BackfillBudgetExhausted:
                raise
            except Exception as exc:
                logger.exception(
                    "PAIR_WORKER_FAILED article_id=%d stock_code=%s", article_id, stock_code
                )
                repo.finish_backfill_pair(
                    run_key,
                    article_id,
                    stock_code,
                    status="pending_retry",
                    error=f"{type(exc).__name__}: {exc}",
                )
                result = {
                    "scanned": 1,
                    "pairs_scanned": 1,
                    "pending_retry": 1,
                }
            current = totals.add(result)
            if current.get("pairs_scanned", 0) % max(1, log_every) == 0:
                logger.info(
                    "ASSIGN_PROGRESS pairs=%d new=%d existing=%d pending=%d calls=%d",
                    current.get("pairs_scanned", 0),
                    current.get("assigned_new", 0),
                    current.get("assigned_existing", 0),
                    current.get("pending_retry", 0),
                    budget.assignment_calls,
                )
                repo.update_backfill_run(
                    run_key,
                    status="running",
                    totals={**current, "phase": "assignment"},
                    usage=add_usage(usage_base or {}, budget.snapshot()),
                )

    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="assign") as executor:
        futures = [executor.submit(process_stock, rows) for rows in by_stock.values()]
        for future in as_completed(futures):
            future.result()
    return totals.snapshot()


def run_summary_phase(
    dirty_rows: list[dict[str, Any]],
    *,
    run_key: str,
    workers: int,
    budget: SolarBackfillBudget,
    gate: AdaptiveSolarGate,
    log_every: int,
    usage_base: dict[str, Any] | None = None,
) -> dict[str, int]:
    totals = SharedTotals()

    def summarize_one(dirty: dict[str, Any]) -> None:
        gate.ensure_running()
        repo = NewsClusterRepository(create_supabase_client(), settings)
        cluster_id = int(dirty["cluster_id"])
        retry_count = int(dirty.get("retry_count") or 0) + 1
        repo.mark_dirty_processing(run_key, cluster_id)
        cluster_rows = (
            repo.client.table("news_clusters")
            .select("stock_code")
            .eq("id", cluster_id)
            .limit(1)
            .execute()
            .data
            or []
        )
        if not cluster_rows:
            repo.mark_dirty_retry(run_key, cluster_id, retry_count, "cluster missing")
            totals.add({"summary_pending_retry": 1})
            return
        stock_code = cluster_rows[0]["stock_code"]
        articles = repo.get_cluster_articles(cluster_id)
        prompt = summarize.build_user_prompt(
            articles[: cluster_cfg.MAX_ARTICLES_PER_SUMMARY],
            STOCK_NAMES.get(stock_code, stock_code),
        )
        try:
            parsed, meta = gate.call(lambda: budget.call_summary(settings.upstage_api_key, prompt))
            repo.save_summary(cluster_id, parsed, meta, retry_count)
            if meta.get("ok") and meta.get("parse_success"):
                repo.mark_dirty_success(run_key, cluster_id)
                current = totals.add({"summary_success": 1})
            else:
                error = str(meta.get("raw") or "invalid summary response")
                repo.mark_dirty_retry(run_key, cluster_id, retry_count, error)
                current = totals.add({"summary_pending_retry": 1})
        except BackfillBudgetExhausted:
            raise
        except Exception as exc:
            repo.save_summary(
                cluster_id,
                {},
                {"ok": False, "parse_success": False, "raw": str(exc)},
                retry_count,
            )
            repo.mark_dirty_retry(run_key, cluster_id, retry_count, f"{type(exc).__name__}: {exc}")
            current = totals.add({"summary_pending_retry": 1})
        done = current.get("summary_success", 0) + current.get("summary_pending_retry", 0)
        if done % max(1, log_every) == 0:
            logger.info(
                "SUMMARY_PROGRESS done=%d success=%d pending=%d calls=%d",
                done,
                current.get("summary_success", 0),
                current.get("summary_pending_retry", 0),
                budget.summary_calls,
            )
            repo.update_backfill_run(
                run_key,
                status="running",
                totals={**current, "phase": "summary"},
                usage=add_usage(usage_base or {}, budget.snapshot()),
            )

    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="summary") as executor:
        futures = [executor.submit(summarize_one, row) for row in dirty_rows]
        for future in as_completed(futures):
            future.result()
    return totals.snapshot()


def main() -> int:
    args = parse_args()
    if not args.execute:
        raise SystemExit("full backfill requires --execute")
    if not settings.use_llm_assign:
        raise SystemExit("USE_LLM_ASSIGN must be true")
    if not 1 <= args.workers <= 4:
        raise SystemExit("workers must be between 1 and 4")
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        force=True,
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    started_at = datetime.now(UTC)
    started = time.monotonic()
    client = get_supabase_client()
    repo = NewsClusterRepository(client, settings)
    previous = repo.get_backfill_run(args.run_key)
    previous_usage = {
        "assignment_calls": int((previous or {}).get("assignment_calls") or 0),
        "summary_calls": int((previous or {}).get("summary_calls") or 0),
        "prompt_tokens": int((previous or {}).get("prompt_tokens") or 0),
        "completion_tokens": int((previous or {}).get("completion_tokens") or 0),
        "cost_usd": float((previous or {}).get("estimated_cost_usd") or 0),
    }
    inventory = collect_inventory(client, include_rows=True)
    target_company_pairs = int(inventory["expected_kind_pairs"]["company"])
    limits = {
        "mode": "two_phase_deferred_summary",
        "workers": args.workers,
        "assignment_call_cap": target_company_pairs,
        "cost_cap": None,
    }
    repo.start_backfill_run(args.run_key, limits)
    if previous and previous.get("status") in {"stopped", "failed", "stopped_budget"}:
        repo.release_backfill_claims(args.run_key, "released when resuming stopped run")
    heartbeat_stop = threading.Event()
    heartbeat_phase = ["preflight"]

    def heartbeat() -> None:
        heartbeat_repo = NewsClusterRepository(create_supabase_client(), settings)
        while not heartbeat_stop.wait(60):
            try:
                heartbeat_repo.heartbeat_backfill(args.run_key, heartbeat_phase[0])
            except Exception:  # the next successful DB write also refreshes the lock
                logger.exception("BACKFILL_HEARTBEAT_FAILED")

    threading.Thread(target=heartbeat, name="backfill-heartbeat", daemon=True).start()
    embedder = BgeM3Embedder(settings.news_embedding_device)
    assignment_budget = SolarBackfillBudget(
        max_assignment_calls=max(1, target_company_pairs),
        max_summary_calls=0,
        max_run_cost_usd=1_000_000,
        max_daily_cost_usd=1_000_000,
        min_interval_seconds=settings.news_backfill_solar_min_interval_seconds,
    )
    assignment_gate = AdaptiveSolarGate(args.workers)
    assignment_totals: dict[str, int] = {}

    try:
        if not previous or int(previous.get("assignment_calls") or 0) == 0:
            preflight = find_company_candidate_pilots(
                repo,
                list(inventory["unassigned_rows"]),
                count=args.preflight_pairs,
                scan_pairs=args.preflight_scan_pairs,
            )
            if len(preflight) < args.preflight_pairs:
                raise RuntimeError("preflight could not find enough real company candidates")
            preflight.sort(
                key=lambda row: (
                    row["stock_code"],
                    row.get("published_at") or "",
                    int(row["article_id"]),
                )
            )
            preflight_totals = run_assignment_phase(
                preflight,
                run_key=args.run_key,
                workers=args.workers,
                budget=assignment_budget,
                gate=assignment_gate,
                embedder=embedder,
                log_every=args.log_every,
                usage_base=previous_usage,
            )
            print(
                "FULL_BACKFILL_PREFLIGHT="
                + json.dumps(preflight_totals, ensure_ascii=False, sort_keys=True),
                flush=True,
            )
            if int(preflight_totals.get("assigned_existing") or 0) == 0:
                raise RuntimeError(
                    "preflight assigned_existing=0; inspect prompt/candidate data before full run"
                )
            assignment_totals = preflight_totals

        heartbeat_phase[0] = "assignment"
        candidates = repo.get_pipeline_candidates(int(inventory["unassigned_pairs"]) + 100)
        rows = flatten_candidates(candidates)
        if rows:
            remaining_totals = run_assignment_phase(
                rows,
                run_key=args.run_key,
                workers=args.workers,
                budget=assignment_budget,
                gate=assignment_gate,
                embedder=embedder,
                log_every=args.log_every,
                usage_base=previous_usage,
            )
            for key, value in remaining_totals.items():
                assignment_totals[key] = assignment_totals.get(key, 0) + value

        repo.update_backfill_run(
            args.run_key,
            status="running",
            totals={**assignment_totals, "phase": "summary"},
            usage=add_usage(previous_usage, assignment_budget.snapshot()),
        )
        repaired_dirty = repo.repair_backfill_dirty_clusters(args.run_key)
        logger.info("DIRTY_REPAIR upserted=%d", repaired_dirty)
        dirty_rows = repo.get_dirty_clusters(args.run_key)
        heartbeat_phase[0] = "summary"
        summary_budget = SolarBackfillBudget(
            max_assignment_calls=0,
            max_summary_calls=max(1, len(dirty_rows)),
            max_run_cost_usd=1_000_000,
            max_daily_cost_usd=1_000_000,
            min_interval_seconds=settings.news_backfill_solar_min_interval_seconds,
        )
        summary_gate = AdaptiveSolarGate(args.workers)
        summary_totals = run_summary_phase(
            dirty_rows,
            run_key=args.run_key,
            workers=args.workers,
            budget=summary_budget,
            gate=summary_gate,
            log_every=args.log_every,
            usage_base=add_usage(previous_usage, assignment_budget.snapshot()),
        )
        totals: dict[str, Any] = {
            **assignment_totals,
            **summary_totals,
            "phase": "completed",
            "dirty_unique_clusters": len(dirty_rows),
        }
        usage = add_usage(previous_usage, combined_usage(assignment_budget, summary_budget))
        repo.update_backfill_run(
            args.run_key,
            status="completed",
            totals=totals,
            usage=usage,
        )
        result = {
            "run_key": args.run_key,
            "started_at": started_at.isoformat(),
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "target": {key: value for key, value in inventory.items() if key != "unassigned_rows"},
            "assignment": assignment_totals,
            "summary": summary_totals,
            "dirty_unique_clusters": len(dirty_rows),
            "usage": usage,
            "assignment_gate": assignment_gate.snapshot(),
            "summary_gate": summary_gate.snapshot(),
        }
        print("FULL_BACKFILL_RESULT=" + json.dumps(result, ensure_ascii=False, sort_keys=True))
        heartbeat_stop.set()
        return 0
    except KeyboardInterrupt:
        heartbeat_stop.set()
        repo.release_backfill_claims(args.run_key, "KeyboardInterrupt")
        repo.update_backfill_run(
            args.run_key,
            status="stopped",
            totals={**assignment_totals, "phase": "interrupted"},
            usage=add_usage(previous_usage, assignment_budget.snapshot()),
            last_error="KeyboardInterrupt",
        )
        raise
    except Exception as exc:
        heartbeat_stop.set()
        repo.release_backfill_claims(args.run_key, f"{type(exc).__name__}: {exc}")
        repo.update_backfill_run(
            args.run_key,
            status="failed",
            totals={**assignment_totals, "phase": "failed"},
            usage=add_usage(previous_usage, assignment_budget.snapshot()),
            last_error=f"{type(exc).__name__}: {exc}",
        )
        raise


if __name__ == "__main__":
    raise SystemExit(main())
