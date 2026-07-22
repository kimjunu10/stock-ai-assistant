"""전체 활성 뉴스 사건 인덱싱 (Phase 2 마무리).

- fetch_active_clusters(전건, 페이지네이션) → 배치 단위 인덱싱
- 해시 기반 중복 방지 유지(이미 인덱싱된 사건은 skip)
- rag_ingestion_runs 에 실행/건수/추정비용 기록
- 실패 사건 목록을 docs/rag/phase_2/index_failures.json 에 저장
- 결과 요약을 docs/rag/phase_2/full_index_result.json 에 저장

usage:
  uv run python scripts/rag_index_news.py [--batch 200] [--dry-run]

비용은 Upstage Embed 2 공개 단가를 코드 상수로 두고 추정치만 기록한다(참고용).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from datetime import UTC, datetime

from app.core.config import settings  # noqa: E402
from app.db.client import get_supabase_client  # noqa: E402
from app.ml.embeddings import UpstageEmbedder  # noqa: E402
from app.rag.chunking import chunk_news_event  # noqa: E402
from app.rag.indexing import SOURCE_TYPE, NewsEventIndexer  # noqa: E402
from app.repositories.rag import RagRepository  # noqa: E402

OUT_DIR = Path(__file__).resolve().parents[1] / "docs" / "rag" / "phase_2"

# Upstage Embed 2 참고 단가(추정용). 실제 청구액은 콘솔 기준. (USD per 1M tokens)
_EMBED_USD_PER_M_TOKENS = 0.10
_CHARS_PER_TOKEN = 2.5  # 한국어 대략치


def estimate_embed_tokens(clusters: list[dict]) -> int:
    total_chars = 0
    for c in clusters:
        for ch in chunk_news_event(
            summary_title=c.get("summary_title"),
            easy_explanation=c.get("easy_explanation"),
            factual_body=c.get("factual_body"),
        ):
            total_chars += len(ch.content)
    return int(total_chars / _CHARS_PER_TOKEN)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--batch", type=int, default=200)
    ap.add_argument("--dry-run", action="store_true", help="조회/추정만, 임베딩·저장 안 함")
    args = ap.parse_args()

    db = get_supabase_client()
    repo = RagRepository(db, settings)
    embedder = UpstageEmbedder(settings)
    indexer = NewsEventIndexer(db, settings, repo, embedder)

    clusters = indexer.fetch_active_clusters(limit=None)
    total = len(clusters)
    est_tokens = estimate_embed_tokens(clusters)
    est_cost = round(est_tokens / 1_000_000 * _EMBED_USD_PER_M_TOKENS, 4)
    print(
        f"활성 사건: {total}건, 추정 임베딩 토큰: {est_tokens:,}, "
        f"추정 비용(전체 재임베딩 기준): ${est_cost}"
    )

    if args.dry_run:
        return 0

    run_id = repo.start_ingestion_run(
        SOURCE_TYPE,
        config={"batch": args.batch, "total_candidates": total, "est_tokens": est_tokens},
    )

    agg = {
        "processed": 0,
        "indexed": 0,
        "skipped_unchanged": 0,
        "chunks_written": 0,
        "embedded_chunks": 0,
        "failures": 0,
    }
    t0 = time.perf_counter()
    for start in range(0, total, args.batch):
        batch = clusters[start : start + args.batch]
        r = indexer.index_clusters(batch)
        for k in agg:
            agg[k] += getattr(r, k)
        done = start + len(batch)
        print(
            f"[{done}/{total}] indexed={agg['indexed']} "
            f"skip={agg['skipped_unchanged']} chunks={agg['chunks_written']} "
            f"fail={agg['failures']}"
        )

    elapsed = round(time.perf_counter() - t0, 1)
    # 실제 임베딩한 청크만 비용에 반영(중복 skip 청크는 임베딩 안 함).
    # 전체 청크 대비 임베딩 청크 비율로 추정 토큰을 안분한다.
    total_chunks_est = sum(
        len(
            chunk_news_event(
                summary_title=c.get("summary_title"),
                easy_explanation=c.get("easy_explanation"),
                factual_body=c.get("factual_body"),
            )
        )
        for c in clusters
    )
    embedded_ratio = agg["embedded_chunks"] / max(1, total_chunks_est)
    actual_cost = round(est_tokens * embedded_ratio / 1_000_000 * _EMBED_USD_PER_M_TOKENS, 4)

    repo.finish_ingestion_run(
        run_id,
        status="success" if agg["failures"] == 0 else "partial",
        finished_at=datetime.now(UTC).isoformat(),
        processed_count=agg["processed"],
        success_count=agg["indexed"] + agg["skipped_unchanged"],
        failure_count=agg["failures"],
        estimated_cost=est_cost,
        actual_cost=actual_cost,
    )

    result = {
        "total_active_events": total,
        **agg,
        "elapsed_seconds": elapsed,
        "estimated_cost_usd_full": est_cost,
        "actual_cost_usd_embedded": actual_cost,
        "ingestion_run_id": run_id,
        "note": "비용은 Upstage Embed 2 참고 단가 기반 추정치. 실제 청구액은 콘솔 기준.",
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "full_index_result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
