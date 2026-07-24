"""Backfill FISA sentiment for finalized cluster summaries.

Usage:
    uv run python -m scripts.backfill_news_sentiment --batch-size 32
    uv run python -m scripts.backfill_news_sentiment --batch-size 32 --force
"""

from __future__ import annotations

import argparse
import json
import logging
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from app.core.config import settings
from app.db.client import get_supabase_client
from app.repositories.news_v2 import V2_VERSION, NewsV2Repository
from app.services.news_sentiment import (
    NewsSentimentService,
    build_sentiment_input,
    sentiment_input_hash,
    sentiment_state_is_current,
)

logger = logging.getLogger("backfill_news_sentiment")
SEOUL_TIMEZONE = ZoneInfo("Asia/Seoul")


def _date_bounds_utc(value: str) -> tuple[str, str]:
    selected = date.fromisoformat(value)
    start = datetime.combine(selected, time.min, tzinfo=SEOUL_TIMEZONE)
    end = start + timedelta(days=1)
    return start.astimezone(UTC).isoformat(), end.astimezone(UTC).isoformat()


def run_backfill(
    repo: NewsV2Repository,
    service: NewsSentimentService,
    *,
    batch_size: int,
    force: bool,
    published_since: str | None = None,
    published_before: str | None = None,
) -> dict[str, int]:
    totals = {"scanned": 0, "success": 0, "failed": 0, "skipped": 0}
    after_id = 0
    while True:
        query = {"after_id": after_id, "batch_size": batch_size}
        if published_since:
            query["published_since"] = published_since
        if published_before:
            query["published_before"] = published_before
        rows = repo.get_sentiment_backfill_batch(**query)
        if not rows:
            break
        after_id = int(rows[-1]["id"])
        selected: list[tuple[dict[str, Any], str]] = []
        for row in rows:
            totals["scanned"] += 1
            model_input = build_sentiment_input(
                row.get("summary_title"),
                row.get("easy_explanation"),
            )
            if not model_input:
                totals["skipped"] += 1
                continue
            if not force and sentiment_state_is_current(
                row,
                row.get("summary_title"),
                row.get("easy_explanation"),
                service,
            ):
                totals["skipped"] += 1
                continue
            selected.append((row, model_input))

        if not selected:
            continue
        results = service.analyze_batch([model_input for _row, model_input in selected])
        for (row, _model_input), result in zip(selected, results, strict=True):
            cluster_id = int(row["id"])
            try:
                repo.save_cluster_sentiment(
                    cluster_id,
                    result,
                    input_hash=sentiment_input_hash(
                        row.get("summary_title"),
                        row.get("easy_explanation"),
                    ),
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
    parser.add_argument(
        "--date",
        help="서울 기준 특정 날짜(YYYY-MM-DD)에 최초 발행된 클러스터만 처리",
    )
    args = parser.parse_args()
    if not 1 <= args.batch_size <= 256:
        parser.error("--batch-size must be between 1 and 256")
    published_since = None
    published_before = None
    if args.date:
        try:
            published_since, published_before = _date_bounds_utc(args.date)
        except ValueError:
            parser.error("--date must be a valid YYYY-MM-DD date")

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    service = NewsSentimentService(settings)
    if not service.load():
        logger.error("NEWS_SENTIMENT_BACKFILL_ABORTED error=%s", service.load_error)
        return 1
    repo = NewsV2Repository(get_supabase_client(), settings, version=V2_VERSION)
    totals = run_backfill(
        repo,
        service,
        batch_size=args.batch_size,
        force=args.force,
        published_since=published_since,
        published_before=published_before,
    )
    print("NEWS_SENTIMENT_BACKFILL_RESULT=" + json.dumps(totals, sort_keys=True))
    return 0 if totals["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
