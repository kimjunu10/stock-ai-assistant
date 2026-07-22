"""News collection and body-crawl orchestration."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

from app.core.config import Settings
from app.repositories.news import NewsRepository
from app.sources.crawler import ArticleCrawler
from app.sources.naver_news import NaverNewsClient
from app.sources.publishers import is_allowed_news_url

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class StockTarget:
    code: str
    name: str


STOCK_TARGETS = (
    StockTarget("005930", "삼성전자"),
    StockTarget("000660", "SK하이닉스"),
    StockTarget("034020", "두산에너빌리티"),
    StockTarget("042660", "한화오션"),
    StockTarget("005380", "현대차"),
)


def collect_search_results(
    *,
    repo: NewsRepository,
    naver: NaverNewsClient,
    max_per_stock: int,
    stock_rounds: int = 2,
) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    """Collect every stock independently and retry failed stocks after the round."""

    remaining = list(STOCK_TARGETS)
    completed: dict[str, dict[str, Any]] = {}
    errors: dict[str, str] = {}

    for round_number in range(1, stock_rounds + 1):
        if not remaining:
            break
        failed: list[StockTarget] = []
        for stock in remaining:
            try:
                logger.info(
                    "SEARCH_START stock=%s code=%s round=%d",
                    stock.name,
                    stock.code,
                    round_number,
                )
                result = naver.search_latest(stock.name, max_results=max_per_stock)
                allowed_items = [
                    item for item in result.items if is_allowed_news_url(item.original_url)
                ]
                filtered_out = len(result.items) - len(allowed_items)
                persisted = repo.upsert_search_items(
                    stock_code=stock.code,
                    query=stock.name,
                    items=allowed_items,
                )
                completed[stock.code] = {
                    "name": stock.name,
                    "pages": result.pages_requested,
                    "raw": result.raw_items_received,
                    "api_total": result.api_total,
                    "filtered_out": filtered_out,
                    **persisted,
                }
                errors.pop(stock.code, None)
                logger.info(
                    "SEARCH_DONE stock=%s pages=%d raw=%d filtered_out=%d unique=%d linked=%d",
                    stock.name,
                    result.pages_requested,
                    result.raw_items_received,
                    filtered_out,
                    persisted["unique"],
                    persisted["linked"],
                )
            except Exception as exc:  # noqa: BLE001 - isolate one stock from the rest
                errors[stock.code] = f"{type(exc).__name__}: {exc}"
                failed.append(stock)
                logger.exception("SEARCH_FAILED stock=%s round=%d", stock.name, round_number)
        remaining = failed
    return completed, errors


def crawl_collected_articles(
    *,
    repo: NewsRepository,
    cfg: Settings,
    wait_for_retries: bool,
    max_attempts: int | None = None,
) -> dict[str, int]:
    """Drain the shared article queue without allowing one publisher to stop the run."""

    recovered = repo.reset_stale_processing()
    if recovered:
        logger.warning("Recovered %d stale processing rows", recovered)

    crawler = ArticleCrawler(cfg)
    totals = {"attempted": 0, "success": 0, "failed": 0, "skipped": 0}
    try:
        while True:
            candidates = repo.get_crawl_candidates(cfg.crawl_batch_size)
            if not candidates:
                wait_seconds = repo.seconds_until_next_retry()
                if not wait_for_retries or wait_seconds is None:
                    break
                if wait_seconds > 0:
                    heartbeat = min(30.0, wait_seconds)
                    logger.info("CRAWL_RETRY_WAIT seconds=%.1f", wait_seconds)
                    time.sleep(heartbeat)
                    continue

            for row in candidates:
                if max_attempts is not None and totals["attempted"] >= max_attempts:
                    return totals
                article_id = int(row["id"])
                attempts = int(row.get("crawl_attempts") or 0) + 1
                repo.mark_attempt_started(article_id, attempts)
                try:
                    result = crawler.crawl(row["original_url"])
                except Exception as exc:  # noqa: BLE001 - persist unexpected crawler failures
                    from app.schemas.news import CrawlResult

                    result = CrawlResult(
                        ok=False,
                        requested_url=row["original_url"],
                        error=f"Unexpected crawler error: {type(exc).__name__}: {exc}",
                    )
                    logger.exception("CRAWL_EXCEPTION article_id=%d", article_id)

                repo.mark_crawl_result(article_id, attempts, result)
                totals["attempted"] += 1
                if result.ok:
                    totals["success"] += 1
                elif result.skipped:
                    totals["skipped"] += 1
                else:
                    totals["failed"] += 1

                if totals["attempted"] % 25 == 0:
                    logger.info(
                        "CRAWL_PROGRESS attempted=%d success=%d failed=%d skipped=%d",
                        totals["attempted"],
                        totals["success"],
                        totals["failed"],
                        totals["skipped"],
                    )
                if cfg.crawl_delay_seconds > 0:
                    time.sleep(cfg.crawl_delay_seconds)
    finally:
        crawler.close()
    return totals
