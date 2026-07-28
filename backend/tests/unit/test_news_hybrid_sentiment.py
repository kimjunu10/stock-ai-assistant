from types import SimpleNamespace
from unittest.mock import MagicMock

from app.core.config import Settings
from app.rag.retrieval import HybridRetriever, RetrievedChunk


class _Query:
    def __init__(self, rows):
        self._rows = rows

    def select(self, _columns):
        return self

    def in_(self, _column, _values):
        return self

    def execute(self):
        return SimpleNamespace(data=self._rows)


class _Db:
    def __init__(self, rows, *, fail=False):
        self.rows = rows
        self.fail = fail
        self.tables = []

    def table(self, name):
        self.tables.append(name)
        if self.fail:
            raise RuntimeError("optional metadata lookup failed")
        return _Query(self.rows)


def _news_chunk(cluster_id: str) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=f"news_cluster:{cluster_id}:0",
        document_id=f"news_cluster:{cluster_id}",
        content="뉴스 본문",
        value_kind=None,
        stock_code="005930",
        source_type="news_event",
        published_at="2026-07-25T09:00:00+09:00",
        source_pk=cluster_id,
        title="뉴스 제목",
        publisher=None,
        source_url=None,
        similarity=0.9,
        source_locator={"document_id": f"news_cluster:{cluster_id}"},
    )


def test_hybrid_news_hits_are_hydrated_with_cluster_sentiment():
    db = _Db([{"id": 77, "sentiment_label": "positive"}])
    retriever = HybridRetriever(db, Settings(), MagicMock())
    chunk = _news_chunk("77")

    retriever._hydrate_news_cluster_metadata([chunk])

    assert db.tables == ["news_clusters"]
    assert chunk.source_locator == {
        "document_id": "news_cluster:77",
        "cluster_id": 77,
        "sentiment_label": "positive",
    }


def test_optional_sentiment_lookup_failure_does_not_drop_search_results():
    retriever = HybridRetriever(_Db([], fail=True), Settings(), MagicMock())
    chunk = _news_chunk("78")

    retriever._hydrate_news_cluster_metadata([chunk])

    assert chunk.source_locator == {"document_id": "news_cluster:78"}
