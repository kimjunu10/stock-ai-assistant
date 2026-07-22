"""미요약 v2 사건 클러스터를 원하는 날짜부터 골라 일괄 요약한다.

스케줄러가 news_summary_enabled=false 로 요약을 미뤄둔 뒤, 필요할 때 실행한다.
요약 1회 호출로 title + easy_explanation + factual_body 를 함께 생성한다.

usage:
  # 2026-07-20 이후 활성 사건 중 미요약분만 요약
  uv run python scripts/summarize_v2.py --since 2026-07-20

  # 전체 미요약분 요약(날짜 제한 없음)
  uv run python scripts/summarize_v2.py --all

  # 몇 건인지 미리보기(요약 안 함)
  uv run python scripts/summarize_v2.py --since 2026-07-20 --dry-run
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings  # noqa: E402
from app.db.client import get_supabase_client  # noqa: E402
from app.repositories.news_v2 import V2_VERSION, NewsV2Repository  # noqa: E402
from experiments.exp_b_factual_summaries import config as cluster_cfg  # noqa: E402
from experiments.exp_b_factual_summaries import summarize  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("summarize_v2")


def main() -> int:
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--since", help="이 날짜(YYYY-MM-DD, last_active_at 기준) 이후 사건만")
    g.add_argument("--all", action="store_true", help="날짜 제한 없이 전체 미요약분")
    ap.add_argument("--dry-run", action="store_true", help="건수만 보고 요약 안 함")
    ap.add_argument("--limit", type=int, default=None, help="최대 요약 건수(안전장치)")
    args = ap.parse_args()

    settings.validate_news_collection()
    repo = NewsV2Repository(get_supabase_client(), settings, version=V2_VERSION)

    since = None if args.all else args.since
    clusters = repo.get_v2_clusters(only_unsummarized=True, since=since)
    if args.limit:
        clusters = clusters[: args.limit]

    logger.info("SUMMARIZE_V2 target=%d since=%s dry_run=%s", len(clusters), since, args.dry_run)
    if args.dry_run:
        print(f"요약 대상(미요약) {len(clusters)}건 (since={since or '전체'})")
        return 0

    stock_names = repo.get_stock_names()
    ok = 0
    failed = 0
    calls = 0
    for i, c in enumerate(clusters, 1):
        cid = int(c["id"])
        articles = repo.get_v2_cluster_articles(cid)[: cluster_cfg.MAX_ARTICLES_PER_SUMMARY]
        if not articles:
            continue
        name = stock_names.get(c["stock_code"], c["stock_code"])
        prompt = summarize.build_user_prompt(articles, name)
        try:
            parsed, meta = summarize.call_solar(settings.upstage_api_key, prompt)
            calls += 1
        except Exception as exc:  # noqa: BLE001 - 개별 격리·재시도
            parsed, meta = {}, {"ok": False, "parse_success": False, "raw": str(exc)}
        repo.save_v2_summary(cid, parsed, meta, 1)
        if meta.get("ok") and meta.get("parse_success"):
            ok += 1
        else:
            failed += 1
        if i % 50 == 0:
            logger.info("  progress %d/%d (ok=%d failed=%d)", i, len(clusters), ok, failed)

    print(f"요약 완료: ok={ok} failed={failed} solar_calls={calls} (since={since or '전체'})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
