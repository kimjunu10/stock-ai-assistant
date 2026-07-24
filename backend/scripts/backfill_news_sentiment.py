"""Backfill FISA sentiment for finalized cluster summary titles.

Usage:
    uv run python -m scripts.backfill_news_sentiment --batch-size 32
    uv run python -m scripts.backfill_news_sentiment --batch-size 32 --force
"""

from __future__ import annotations

import argparse
import json
import logging
from typing import Any

from app.core.config import settings
from app.db.client import get_supabase_client
from app.repositories.news_v2 import V2_VERSION, NewsV2Repository
from app.services.news_sentiment import (
    NewsSentimentService,
    normalize_sentiment_title,
    sentiment_input_hash,
    sentiment_state_is_current,
)

logger = logging.getLogger("backfill_news_sentiment")


def run_backfill(
    repo: NewsV2Repository,
    service: NewsSentimentService,
    *,
    batch_size: int,
    force: bool,
) -> dict[str, int]:
    totals = {"scanned": 0, "success": 0, "failed": 0, "skipped": 0}
    after_id = 0
    while True:
        rows = repo.get_sentiment_backfill_batch(after_id=after_id, batch_size=batch_size)
        if not rows:
            break
        after_id = int(rows[-1]["id"])
        selected: list[tuple[dict[str, Any], str]] = []
        for row in rows:
            totals["scanned"] += 1
            title = normalize_sentiment_title(row.get("summary_title"))
            if not title:
                totals["skipped"] += 1
                continue
            if not force and sentiment_state_is_current(row, title, service):
                totals["skipped"] += 1
                continue
            selected.append((row, title))

        if not selected:
            continue
        results = service.analyze_batch([title for _row, title in selected])
        for (row, title), result in zip(selected, results, strict=True):
            cluster_id = int(row["id"])
            try:
                repo.save_cluster_sentiment(
                    cluster_id,
                    result,
                    input_hash=sentiment_input_hash(title),
                )
                if result.label == "unknown":
                    totals["failed"] += 1
                    logger.warning(
                        "NEWS_SENTIMENT_BACKFILL_UNKNOWN cluster_id=%d error=%s",
                        cluster_id,
                        result.error or "unknown",
                    )
                else:
                    totals["success"] += 1
            except Exception as exc:  # noqa: BLE001 - resume skips already persisted rows
                totals["failed"] += 1
                logger.exception(
                    "NEWS_SENTIMENT_BACKFILL_SAVE_FAILED cluster_id=%d error=%s",
                    cluster_id,
                    exc,
                )
    return totals


def main() -> int:
    parser = argparse.ArgumentParser(description="뉴스 클러스터 FISA 감성분류 backfill")
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    if not 1 <= args.batch_size <= 256:
        parser.error("--batch-size must be between 1 and 256")

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    service = NewsSentimentService(settings)
    if not service.load():
        logger.error("NEWS_SENTIMENT_BACKFILL_ABORTED error=%s", service.load_error)
        return 1
    repo = NewsV2Repository(get_supabase_client(), settings, version=V2_VERSION)
    totals = run_backfill(repo, service, batch_size=args.batch_size, force=args.force)
    print("NEWS_SENTIMENT_BACKFILL_RESULT=" + json.dumps(totals, sort_keys=True))
    return 0 if totals["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
