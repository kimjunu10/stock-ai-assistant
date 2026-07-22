"""In-process scheduling for recurring backend collection jobs."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, TypeVar
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.core.config import Settings, settings
from app.db.client import get_supabase_client
from app.jobs.news import collect_search_results, crawl_collected_articles
from app.repositories.news import NewsRepository
from app.repositories.news_clusters import NewsClusterRepository
from app.repositories.news_v2 import V2_VERSION, NewsV2Repository
from app.sources.naver_news import NaverNewsClient
from experiments.exp_b_factual_summaries.assign_llm_v2 import ASSIGN_V2_PROMPT_VERSION
from scripts.run_full_news_v2 import phase_cluster, phase_roles, phase_summary, phase_verify

logger = logging.getLogger("uvicorn.error.news_scheduler")

NEWS_COLLECTION_JOB_ID = "news-collection"
SEOUL_TIMEZONE = ZoneInfo("Asia/Seoul")
T = TypeVar("T")


def _run_news_stage(stage: str, operation: Callable[[], T]) -> T:
    """Run one cycle stage with concise lifecycle and failure logging."""

    started_at = time.monotonic()
    logger.info("NEWS_STAGE_START stage=%s", stage)
    try:
        result = operation()
    except Exception:  # noqa: BLE001 - log the stage, then let APScheduler record the failure
        logger.exception(
            "NEWS_STAGE_FAILED stage=%s elapsed_seconds=%.3f",
            stage,
            time.monotonic() - started_at,
        )
        raise
    logger.info(
        "NEWS_STAGE_DONE stage=%s elapsed_seconds=%.3f",
        stage,
        time.monotonic() - started_at,
    )
    return result


def run_news_collection_cycle(cfg: Settings = settings) -> dict[str, Any]:
    """Fetch the latest search window and crawl only DB-eligible articles."""

    started_at = datetime.now(UTC)
    logger.info(
        "NEWS_CYCLE_START max_per_stock=%d",
        cfg.news_scheduler_max_per_stock,
    )

    def setup_repositories() -> tuple[NewsRepository, NewsClusterRepository, NewsV2Repository]:
        cfg.validate_news_collection()
        repo = NewsRepository(get_supabase_client(), cfg)
        return (
            repo,
            NewsClusterRepository(repo.client, cfg),
            NewsV2Repository(repo.client, cfg, version=V2_VERSION),
        )

    repo, cluster_guard, v2_repo = _run_news_stage("setup", setup_repositories)

    def collect() -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
        naver = NaverNewsClient(cfg)
        try:
            return collect_search_results(
                repo=repo,
                naver=naver,
                max_per_stock=cfg.news_scheduler_max_per_stock,
            )
        finally:
            naver.close()

    collected, errors = _run_news_stage("search", collect)
    crawl_totals = _run_news_stage(
        "crawl",
        lambda: crawl_collected_articles(
            repo=repo,
            cfg=cfg,
            wait_for_retries=False,
        ),
    )
    relevance_totals = _run_news_stage("relevance", repo.classify_pending_relevance)
    v2_totals = {
        "role_classified": 0,
        "role_rule": 0,
        "role_llm": 0,
        "role_pending": 0,
        "assigned_new": 0,
        "assigned_existing": 0,
        "cluster_pending": 0,
        "cluster_skipped": 0,
        "assign_llm_calls": 0,
        "summaries": 0,
        "summary_failed": 0,
    }
    has_active_backfill = _run_news_stage("backfill_guard", cluster_guard.has_active_backfill)
    if has_active_backfill:
        logger.info("NEWS_CLUSTERING_SKIPPED active_backfill=true")
        v2_totals["skipped_active_backfill"] = 1
    else:
        new_event_pairs = _run_news_stage(
            "roles", lambda: phase_roles(v2_repo, v2_totals, workers=1)
        )
        _run_news_stage(
            "cluster",
            lambda: phase_cluster(v2_repo, v2_totals, candidates=new_event_pairs),
        )
        _run_news_stage("summary", lambda: phase_summary(v2_repo, v2_totals))
        v2_ok, v2_problems = _run_news_stage("verify", lambda: phase_verify(v2_repo, v2_totals))
        v2_totals["verification_ok"] = int(v2_ok)
        if v2_problems:
            logger.warning("NEWS_V2_INCOMPLETE problems=%s", "; ".join(v2_problems))
    elapsed_seconds = (datetime.now(UTC) - started_at).total_seconds()
    result = {
        "collected": collected,
        "errors": errors,
        "crawl": crawl_totals,
        "relevance": relevance_totals,
        "clustering": v2_totals,
        "elapsed_seconds": round(elapsed_seconds, 3),
    }
    logger.info(
        "NEWS_CYCLE_DONE stocks=%d search_errors=%d attempted=%d success=%d "
        "failed=%d skipped=%d elapsed_seconds=%.3f",
        len(collected),
        len(errors),
        crawl_totals["attempted"],
        crawl_totals["success"],
        crawl_totals["failed"],
        crawl_totals["skipped"],
        elapsed_seconds,
    )
    logger.info(
        "NEWS_RELEVANCE scanned=%d relevant=%d irrelevant=%d deferred=%d updated=%d",
        relevance_totals["scanned"],
        relevance_totals["relevant"],
        relevance_totals["irrelevant"],
        relevance_totals["deferred"],
        relevance_totals["updated"],
    )
    logger.info(
        "NEWS_V2 roles=%d role_pending=%d assigned_new=%d assigned_existing=%d "
        "cluster_pending=%d summaries=%d summary_failed=%d prompt_version=%s",
        v2_totals["role_classified"],
        v2_totals["role_pending"],
        v2_totals["assigned_new"],
        v2_totals["assigned_existing"],
        v2_totals["cluster_pending"],
        v2_totals["summaries"],
        v2_totals["summary_failed"],
        ASSIGN_V2_PROMPT_VERSION,
    )
    return result


def build_scheduler(cfg: Settings = settings) -> AsyncIOScheduler:
    """Build the scheduler without starting it, which keeps app startup testable."""

    scheduler = AsyncIOScheduler(timezone=SEOUL_TIMEZONE)
    if not cfg.news_scheduler_enabled:
        logger.info("News scheduler is disabled")
        return scheduler

    scheduler.add_job(
        run_news_collection_cycle,
        trigger=IntervalTrigger(
            minutes=cfg.news_scheduler_interval_minutes,
            timezone=SEOUL_TIMEZONE,
        ),
        args=(cfg,),
        id=NEWS_COLLECTION_JOB_ID,
        name="Collect latest Naver news",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
        misfire_grace_time=max(
            60,
            min(cfg.news_scheduler_interval_minutes * 60, 15 * 60),
        ),
    )
    return scheduler
