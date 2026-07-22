"""뉴스 사건 RAG 증분 인덱싱 잡 (스케줄러 사이클 말미에 호출).

역할:
- summary/verify 이후 활성 사건을 RAG 인덱스에 반영한다.
- 신규·변경 사건만 처리하고, 기존 사건은 content_hash 로 skip(인덱서가 담당).
- 뉴스 수집/클러스터링 전체를 중단시키지 않도록 예외를 완전히 격리한다.
- 여러 프로세스·인스턴스에서 동시에 떠도 중복 인덱싱을 막는다:
    DATABASE_URL 이 있으면 PostgreSQL advisory lock(프로세스·인스턴스 간),
    없으면 프로세스 내 threading.Lock(fallback).
- 실행/실패를 로그와 rag_ingestion_runs 에 기록한다.
- 기존 뉴스/DART 데이터는 수정하지 않는다(읽기 + rag_* 쓰기만).
"""

from __future__ import annotations

import logging
import threading
from datetime import UTC, datetime
from typing import Any

from app.core.config import Settings
from app.db.advisory_lock import NEWS_RAG_INDEX_LOCK_KEY, advisory_lock
from app.db.client import get_supabase_client
from app.ml.embeddings import UpstageEmbedder
from app.rag.indexing import SOURCE_TYPE, NewsEventIndexer
from app.repositories.rag import RagRepository

logger = logging.getLogger("uvicorn.error.rag_index_job")

# DATABASE_URL 이 없을 때만 쓰는 프로세스-로컬 fallback 락.
_INDEX_LOCK = threading.Lock()

_SKIPPED_LOCKED = {"status": "skipped_locked"}


def run_incremental_news_index(cfg: Settings) -> dict[str, Any]:
    """활성 뉴스 사건을 증분 인덱싱한다. 절대 예외를 밖으로 던지지 않는다.

    동시 실행 방지:
    - DATABASE_URL 있음 → advisory lock 으로 프로세스·인스턴스 간 상호배제.
    - DATABASE_URL 없음 → threading.Lock fallback(단일 프로세스 한정).
    """

    if cfg.database_url:
        with advisory_lock(cfg.database_url, NEWS_RAG_INDEX_LOCK_KEY) as acquired:
            if not acquired:
                logger.info("RAG_INDEX_SKIPPED reason=advisory_lock_busy_or_unavailable")
                return _SKIPPED_LOCKED
            return _do_index(cfg)

    # fallback: DB 잠금을 쓸 수 없는 환경(로컬/테스트 등).
    if not _INDEX_LOCK.acquire(blocking=False):
        logger.info("RAG_INDEX_SKIPPED reason=already_running_threadlock")
        return _SKIPPED_LOCKED
    try:
        return _do_index(cfg)
    finally:
        _INDEX_LOCK.release()


def _do_index(cfg: Settings) -> dict[str, Any]:
    """실제 인덱싱 본체. 예외를 스스로 격리하고 rag_ingestion_runs 에 기록한다."""

    run_id: str | None = None
    repo: RagRepository | None = None
    try:
        db = get_supabase_client()
        repo = RagRepository(db, cfg)
        indexer = NewsEventIndexer(db, cfg, repo, UpstageEmbedder(cfg))

        clusters = indexer.fetch_active_clusters(limit=None)
        run_id = repo.start_ingestion_run(
            SOURCE_TYPE,
            config={"trigger": "scheduler_incremental", "candidates": len(clusters)},
        )

        result = indexer.index_clusters(clusters)

        status = "success" if result.failures == 0 else "partial"
        repo.finish_ingestion_run(
            run_id,
            status=status,
            finished_at=datetime.now(UTC).isoformat(),
            processed_count=result.processed,
            success_count=result.indexed + result.skipped_unchanged,
            failure_count=result.failures,
            error_summary={"failed_source_pks": result.failed_source_pks[:50]},
        )

        logger.info(
            "RAG_INDEX_DONE status=%s processed=%d indexed=%d skipped=%d "
            "chunks=%d failures=%d run_id=%s",
            status,
            result.processed,
            result.indexed,
            result.skipped_unchanged,
            result.chunks_written,
            result.failures,
            run_id,
        )
        if result.failed_source_pks:
            logger.warning(
                "RAG_INDEX_FAILURES cluster_ids=%s",
                ",".join(result.failed_source_pks[:50]),
            )
        return {
            "status": status,
            "processed": result.processed,
            "indexed": result.indexed,
            "skipped_unchanged": result.skipped_unchanged,
            "chunks_written": result.chunks_written,
            "failures": result.failures,
            "failed_source_pks": result.failed_source_pks,
            "run_id": run_id,
        }
    except Exception as exc:  # noqa: BLE001 - 인덱싱 실패가 뉴스 사이클을 막지 않게 격리
        logger.exception("RAG_INDEX_FATAL run_id=%s", run_id)
        if run_id and repo is not None:
            try:
                repo.finish_ingestion_run(
                    run_id,
                    status="failed",
                    finished_at=datetime.now(UTC).isoformat(),
                    error_summary={"fatal": str(exc)[:500]},
                )
            except Exception:  # noqa: BLE001 - 기록 실패도 삼킨다
                logger.exception("RAG_INDEX_RUN_FINALIZE_FAILED run_id=%s", run_id)
        return {"status": "failed", "error": str(exc)[:300]}
