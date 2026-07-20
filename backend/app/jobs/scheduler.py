"""In-process scheduling for recurring backend collection jobs."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.core.config import Settings, settings
from app.db.client import get_supabase_client
from app.jobs.news import collect_search_results, crawl_collected_articles
from app.repositories.news import NewsRepository
from app.sources.naver_news import NaverNewsClient

logger = logging.getLogger("uvicorn.error.news_scheduler")

NEWS_COLLECTION_JOB_ID = "news-collection"
SEOUL_TIMEZONE = ZoneInfo("Asia/Seoul")


def run_news_collection_cycle(cfg: Settings = settings) -> dict[str, Any]:
    """Fetch the latest search window and crawl only DB-eligible articles."""

    started_at = datetime.now(UTC)
    logger.info(
        "NEWS_CYCLE_START max_per_stock=%d",
        cfg.news_scheduler_max_per_stock,
    )
    cfg.validate_news_collection()
    repo = NewsRepository(get_supabase_client(), cfg)
    naver = NaverNewsClient(cfg)
    try:
        collected, errors = collect_search_results(
            repo=repo,
            naver=naver,
            max_per_stock=cfg.news_scheduler_max_per_stock,
        )
    finally:
        naver.close()

    crawl_totals = crawl_collected_articles(
        repo=repo,
        cfg=cfg,
        wait_for_retries=False,
    )
    elapsed_seconds = (datetime.now(UTC) - started_at).total_seconds()
    result = {
        "collected": collected,
        "errors": errors,
        "crawl": crawl_totals,
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
