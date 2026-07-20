"""Classify pending article-stock links using exact stock names and safe aliases."""

from __future__ import annotations

import argparse
import json

from app.core.config import settings
from app.db.client import get_supabase_client
from app.repositories.news import NewsRepository


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="calculate labels without updating Supabase",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    settings.validate_news_collection()
    repo = NewsRepository(get_supabase_client(), settings)
    summary = repo.classify_pending_relevance(dry_run=args.dry_run)
    print("RELEVANCE_SUMMARY=" + json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
