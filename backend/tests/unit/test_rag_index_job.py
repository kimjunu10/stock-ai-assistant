"""RAG 증분 인덱싱 잡: 자동 반영 / 재실행 skip / 실패 격리 / 동시실행 방지 테스트.

외부 호출(Supabase/Upstage/PostgreSQL)은 monkeypatch 로 대체한다.
동시실행 방지는 두 경로:
  - DATABASE_URL 있음 -> advisory lock (프로세스·인스턴스 간)
  - DATABASE_URL 없음 -> threading.Lock fallback
기존 로직 테스트는 fallback(database_url="") 경로로 고정해 DB 연결을 피한다.
"""

from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import MagicMock

from app.core.config import Settings
from app.jobs import rag_index_job
from app.jobs.rag_index_job import run_incremental_news_index
from app.rag.indexing import IndexResult


def _cfg() -> Settings:
    # DATABASE_URL 을 비워 threading fallback 경로를 타게 한다(DB 연결 회피).
    return Settings(database_url="")


class _FakeRepo:
    """start/finish_ingestion_run 호출을 기록하는 가짜 RagRepository."""

    def __init__(self) -> None:
        self.started = False
        self.finished_fields: dict | None = None

    def start_ingestion_run(self, source_type, config=None):  # noqa: ANN001
        self.started = True
        return "run-123"

    def finish_ingestion_run(self, run_id, **fields):  # noqa: ANN001
        self.finished_fields = fields


def _patch(monkeypatch, *, index_result=None, index_side_effect=None, repo=None):
    repo = repo or _FakeRepo()
    monkeypatch.setattr(rag_index_job, "get_supabase_client", lambda: MagicMock())
    monkeypatch.setattr(rag_index_job, "UpstageEmbedder", lambda cfg: MagicMock())
    monkeypatch.setattr(rag_index_job, "RagRepository", lambda db, cfg: repo)

    fake_indexer = MagicMock()
    fake_indexer.fetch_active_clusters.return_value = [{"id": 1}, {"id": 2}]
    if index_side_effect:
        fake_indexer.index_clusters.side_effect = index_side_effect
    else:
        fake_indexer.index_clusters.return_value = index_result
    monkeypatch.setattr(rag_index_job, "NewsEventIndexer", lambda *a, **k: fake_indexer)
    return repo


def test_incremental_index_reflects_new_events(monkeypatch):
    """자동 반영: 신규 인덱싱 결과가 요약과 ingestion_run 에 기록된다."""
    repo = _patch(
        monkeypatch,
        index_result=IndexResult(
            processed=2, indexed=2, skipped_unchanged=0, chunks_written=3, embedded_chunks=3
        ),
    )
    out = run_incremental_news_index(_cfg())
    assert out["status"] == "success"
    assert out["indexed"] == 2
    assert repo.started is True
    assert repo.finished_fields["status"] == "success"
    assert repo.finished_fields["failure_count"] == 0


def test_incremental_index_skips_unchanged(monkeypatch):
    """재실행 skip: 변경 없는 사건은 skipped 로 집계되고 실패 없이 success."""
    repo = _patch(
        monkeypatch,
        index_result=IndexResult(
            processed=2, indexed=0, skipped_unchanged=2, chunks_written=0, embedded_chunks=0
        ),
    )
    out = run_incremental_news_index(_cfg())
    assert out["status"] == "success"
    assert out["indexed"] == 0
    assert out["skipped_unchanged"] == 2
    assert repo.finished_fields["success_count"] == 2


def test_incremental_index_isolates_fatal_error(monkeypatch):
    """실패 격리: 인덱서가 예외를 던져도 함수는 예외를 밖으로 던지지 않는다."""
    repo = _patch(monkeypatch, index_side_effect=RuntimeError("upstage down"))
    out = run_incremental_news_index(_cfg())  # 예외가 전파되면 여기서 테스트 실패
    assert out["status"] == "failed"
    assert "upstage down" in out["error"]
    assert repo.finished_fields["status"] == "failed"


def test_incremental_index_partial_records_failed_pks(monkeypatch):
    """일부 실패: partial 상태와 실패 cluster id 기록."""
    repo = _patch(
        monkeypatch,
        index_result=IndexResult(processed=2, indexed=1, failures=1, failed_source_pks=["4748"]),
    )
    out = run_incremental_news_index(_cfg())
    assert out["status"] == "partial"
    assert out["failed_source_pks"] == ["4748"]
    assert repo.finished_fields["status"] == "partial"


def test_threadlock_prevents_concurrent_run(monkeypatch):
    """fallback 경로: threading 락이 이미 잡혀 있으면 skipped_locked."""
    _patch(monkeypatch, index_result=IndexResult())
    acquired = rag_index_job._INDEX_LOCK.acquire(blocking=False)
    assert acquired is True
    try:
        out = run_incremental_news_index(_cfg())
        assert out["status"] == "skipped_locked"
    finally:
        rag_index_job._INDEX_LOCK.release()


# --- advisory lock 경로 (DATABASE_URL 있음) ---


def test_advisory_lock_acquired_runs_index(monkeypatch):
    """DATABASE_URL 있음 + advisory lock 획득 → 인덱싱 실행."""
    repo = _patch(monkeypatch, index_result=IndexResult(processed=2, indexed=2))

    @contextmanager
    def fake_lock(url, key):
        assert url == "postgres://x"
        yield True

    monkeypatch.setattr(rag_index_job, "advisory_lock", fake_lock)
    out = run_incremental_news_index(Settings(database_url="postgres://x"))
    assert out["status"] == "success"
    assert out["indexed"] == 2
    assert repo.started is True


def test_advisory_lock_busy_skips(monkeypatch):
    """DATABASE_URL 있음 + advisory lock 이 다른 프로세스에 잡힘 → skipped, 인덱싱 안 함."""
    repo = _patch(monkeypatch, index_result=IndexResult(processed=2, indexed=2))

    @contextmanager
    def busy_lock(url, key):
        yield False  # 다른 프로세스/인스턴스가 보유 중

    monkeypatch.setattr(rag_index_job, "advisory_lock", busy_lock)
    out = run_incremental_news_index(Settings(database_url="postgres://x"))
    assert out["status"] == "skipped_locked"
    assert repo.started is False  # 인덱싱 진입 안 함
