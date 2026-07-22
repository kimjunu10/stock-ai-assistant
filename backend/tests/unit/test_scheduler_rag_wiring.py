"""스케줄러가 뉴스 사이클 말미에 RAG 증분 인덱싱을 자동 호출하는지(연결) +
인덱싱 결과가 사이클 결과에 격리되어 담기는지 검증한다.

무거운 외부 의존성은 monkeypatch 로 무해화한다.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from app.core.config import Settings
from app.jobs import scheduler as sched


def _neutralize(monkeypatch):
    """뉴스 사이클의 외부 의존성을 전부 무해한 mock 으로 대체한다."""

    cfg = Settings(rag_index_on_schedule=True, news_summary_enabled=False)
    # validate_news_collection 은 .env 자격증명으로 통과. 클래스 메서드를 무해화한다.
    monkeypatch.setattr(Settings, "validate_news_collection", lambda self: None)

    monkeypatch.setattr(sched, "get_supabase_client", lambda: MagicMock())
    monkeypatch.setattr(sched, "NewsRepository", lambda *a, **k: MagicMock())
    monkeypatch.setattr(sched, "NewsClusterRepository", lambda *a, **k: MagicMock())
    monkeypatch.setattr(sched, "NewsV2Repository", lambda *a, **k: MagicMock())
    monkeypatch.setattr(sched, "NaverNewsClient", lambda *a, **k: MagicMock())

    monkeypatch.setattr(sched, "collect_search_results", lambda **k: ({}, {}))
    monkeypatch.setattr(
        sched,
        "crawl_collected_articles",
        lambda **k: {"attempted": 0, "success": 0, "failed": 0, "skipped": 0},
    )
    # cluster_guard.has_active_backfill -> False 가 되도록 NewsClusterRepository mock 조정
    guard = MagicMock()
    guard.has_active_backfill.return_value = False
    monkeypatch.setattr(sched, "NewsClusterRepository", lambda *a, **k: guard)

    repo = MagicMock()
    repo.classify_pending_relevance.return_value = {
        "scanned": 0,
        "relevant": 0,
        "irrelevant": 0,
        "deferred": 0,
        "updated": 0,
    }
    repo.client = MagicMock()
    monkeypatch.setattr(sched, "NewsRepository", lambda *a, **k: repo)

    monkeypatch.setattr(sched, "phase_roles", lambda *a, **k: [])
    monkeypatch.setattr(sched, "phase_cluster", lambda *a, **k: None)
    monkeypatch.setattr(sched, "phase_summary", lambda *a, **k: None)
    monkeypatch.setattr(sched, "phase_verify", lambda *a, **k: (True, []))
    return cfg


def test_cycle_calls_incremental_index(monkeypatch):
    cfg = _neutralize(monkeypatch)
    called = {}

    def fake_index(c):
        called["yes"] = True
        return {"status": "success", "indexed": 3}

    monkeypatch.setattr(sched, "run_incremental_news_index", fake_index)

    result = sched.run_news_collection_cycle(cfg)
    assert called.get("yes") is True
    assert result["rag_index"] == {"status": "success", "indexed": 3}


def test_cycle_can_disable_incremental_index(monkeypatch):
    cfg = _neutralize(monkeypatch)
    cfg.rag_index_on_schedule = False
    monkeypatch.setattr(
        sched,
        "run_incremental_news_index",
        lambda c: (_ for _ in ()).throw(AssertionError("should not be called")),
    )

    result = sched.run_news_collection_cycle(cfg)
    assert result["rag_index"]["status"] == "disabled"
