"""Phase 2 시험: 뉴스 사건 100건 인덱싱 + 검색/답변 smoke test.

- 활성 뉴스 사건 최신 N건을 인덱싱(기본 100).
- 인덱싱된 사건에서 뽑은 질문으로 검색 상위 포함 여부 확인.
- 답변 생성/스트리밍 응답시간·인용검증 측정.
- 결과를 backend/docs/rag/phase_2/ 에 저장.
- 실제 뉴스 데이터에만 씀. 새 rag_documents/rag_chunks 만 추가(기존 무변경).

usage:
  uv run python scripts/rag_phase2_trial.py --limit 100 [--reset]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings  # noqa: E402
from app.db.client import get_supabase_client  # noqa: E402
from app.ml.embeddings import UpstageEmbedder  # noqa: E402
from app.ml.generation import SolarGenerator  # noqa: E402
from app.rag.indexing import SOURCE_TYPE, NewsEventIndexer  # noqa: E402
from app.rag.retrieval import SemanticRetriever  # noqa: E402
from app.repositories.rag import RagRepository  # noqa: E402
from app.services.rag_qa import RagQaService  # noqa: E402

OUT_DIR = Path(__file__).resolve().parents[1] / "docs" / "rag" / "phase_2"


def reset_news_index(db) -> int:
    """이전 시험분 news_event 문서/청크 삭제(cascade). 반환: 삭제 문서 수."""

    docs = (
        db.table("rag_documents").select("id").eq("source_type", SOURCE_TYPE).execute().data or []
    )
    for d in docs:
        db.table("rag_documents").delete().eq("id", d["id"]).execute()
    return len(docs)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=100)
    ap.add_argument("--reset", action="store_true", help="기존 news_event 인덱스 삭제 후 재인덱싱")
    ap.add_argument("--questions", type=int, default=5)
    args = ap.parse_args()

    db = get_supabase_client()
    repo = RagRepository(db, settings)
    embedder = UpstageEmbedder(settings)
    indexer = NewsEventIndexer(db, settings, repo, embedder)

    report: dict = {"limit": args.limit}

    if args.reset:
        report["reset_deleted_docs"] = reset_news_index(db)

    clusters = indexer.fetch_active_clusters(limit=args.limit)
    report["fetched_clusters"] = len(clusters)

    t0 = time.perf_counter()
    result = indexer.index_clusters(clusters)
    index_seconds = time.perf_counter() - t0
    report["indexing"] = {
        "processed": result.processed,
        "indexed": result.indexed,
        "skipped_unchanged": result.skipped_unchanged,
        "chunks_written": result.chunks_written,
        "embedded_chunks": result.embedded_chunks,
        "failures": result.failures,
        "seconds": round(index_seconds, 1),
    }

    # --- 검색/답변 smoke: 인덱싱한 사건에서 질문 생성 ---
    retriever = SemanticRetriever(db, settings, embedder)
    service = RagQaService(retriever, SolarGenerator(settings), settings)

    sample = clusters[: args.questions]
    q_reports = []
    for c in sample:
        source_pk = str(c["id"])
        question = c.get("summary_title") or "이 사건이 뭐야?"
        # 1) 검색 상위에 해당 사건이 포함되는가
        hits = retriever.search(question, stock_code=c.get("stock_code"), source_type=SOURCE_TYPE)
        top_pks = [h.source_pk for h in hits]
        in_top = source_pk in top_pks
        rank = top_pks.index(source_pk) + 1 if in_top else None
        # 2) 답변 생성 (응답시간은 ans.latency_ms 에 담김)
        ans = service.answer(question, stock_code=c.get("stock_code"), context_source_id=source_pk)
        q_reports.append(
            {
                "cluster_id": c["id"],
                "stock_code": c.get("stock_code"),
                "question": question,
                "self_in_top": in_top,
                "self_rank": rank,
                "num_sources": len(ans.sources),
                "invalid_citations": ans.invalid_citations,
                "answer_len": len(ans.answer),
                "latency_ms": ans.latency_ms,
                "answer_preview": ans.answer[:280],
            }
        )

    report["questions"] = q_reports
    report["summary"] = {
        "self_in_top_rate": round(
            sum(1 for q in q_reports if q["self_in_top"]) / max(len(q_reports), 1), 2
        ),
        "any_invalid_citation": any(q["invalid_citations"] for q in q_reports),
        "avg_generate_ms": round(
            sum(q["latency_ms"].get("generate", 0) for q in q_reports) / max(len(q_reports), 1)
        ),
    }

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "trial_100_result.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report["indexing"], ensure_ascii=False, indent=2))
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
