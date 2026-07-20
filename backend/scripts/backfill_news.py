"""Backfill the latest Naver results and crawl publisher article bodies."""

from __future__ import annotations

import argparse
import json
import logging

from app.core.config import settings
from app.db.client import get_supabase_client
from app.jobs.news import STOCK_TARGETS, collect_search_results, crawl_collected_articles
from app.repositories.news import NewsRepository
from app.sources.naver_news import NaverNewsClient


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-per-stock", type=int, default=1000)
    parser.add_argument("--skip-search", action="store_true")
    parser.add_argument("--skip-crawl", action="store_true")
    parser.add_argument("--no-wait-for-retries", action="store_true")
    parser.add_argument("--max-crawl-attempts", type=int)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        force=True,
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("trafilatura").setLevel(logging.ERROR)
    settings.validate_news_collection()
    repo = NewsRepository(get_supabase_client(), settings)
    collected = {}
    errors = {}
    if not args.skip_search:
        naver = NaverNewsClient(settings)
        try:
            collected, errors = collect_search_results(
                repo=repo,
                naver=naver,
                max_per_stock=args.max_per_stock,
            )
        finally:
            naver.close()

    if collected:
        print("COLLECTION_SUMMARY=" + json.dumps(collected, ensure_ascii=False, sort_keys=True))
    if errors:
        print("COLLECTION_ERRORS=" + json.dumps(errors, ensure_ascii=False, sort_keys=True))

    crawl_totals = None
    if not args.skip_crawl:
        crawl_totals = crawl_collected_articles(
            repo=repo,
            cfg=settings,
            wait_for_retries=not args.no_wait_for_retries,
            max_attempts=args.max_crawl_attempts,
        )
        print("CRAWL_SUMMARY=" + json.dumps(crawl_totals, ensure_ascii=False, sort_keys=True))

    relevance_totals = repo.classify_pending_relevance()
    print("RELEVANCE_SUMMARY=" + json.dumps(relevance_totals, ensure_ascii=False, sort_keys=True))

    final = {stock.name: repo.get_stock_summary(stock.code) for stock in STOCK_TARGETS}
    print("FINAL_SUMMARY=" + json.dumps(final, ensure_ascii=False, sort_keys=True))
    if errors:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
