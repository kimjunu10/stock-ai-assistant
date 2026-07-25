"""빈 검색어 뉴스 결함 수정 검증(phase_7 PHASE_7_BUG_NEWS_EMPTY_QUERY).

- 임베딩 계층: 빈/공백 입력은 외부 HTTP 호출 없이 내부 입력 오류(ValueError).
- HybridRetriever.list_recent_news: query 없이 종목·기간·감성으로 사건 최신순 조회,
  임베딩 호출 0회, 최신순, 동일 사건 중복 없음, 타 종목 혼입 없음.
"""

from __future__ import annotations

import pytest

from app.core.config import settings as cfg
from app.ml.embeddings import UpstageEmbedder
from app.rag.retrieval import HybridRetriever


# ── 임베딩 입력 방어 ──
class _SpySession:
    """외부 HTTP 가 호출되면 즉시 실패시켜 '호출되지 않음'을 증명한다."""

    def __init__(self):
        self.calls = 0

    def post(self, *a, **k):  # noqa: ANN002, ANN003
        self.calls += 1
        raise AssertionError("외부 임베딩 HTTP 가 호출되면 안 된다")


@pytest.mark.parametrize("bad", ["", "   ", "\n\t"])
def test_embed_rejects_blank_without_http(bad):
    spy = _SpySession()
    emb = UpstageEmbedder(cfg, session=spy)
    with pytest.raises(ValueError):
        emb.embed_query(bad)
    assert spy.calls == 0  # 외부 API 로 안 나감


def test_embed_query_rejects_blank_is_input_error_not_vector():
    """빈 입력을 임의 벡터/문장으로 대체하지 않는다(명확한 입력 오류)."""
    emb = UpstageEmbedder(cfg, session=_SpySession())
    with pytest.raises(ValueError):
        emb.embed_query("")


# ── list_recent_news: query 없는 조건 조회 ──
class _FakeQuery:
    """supabase table().select().eq()... 체인을 흉내내고 필터를 기록한다."""

    def __init__(self, rows, log):
        self._rows = rows
        self._log = log

    def select(self, *a, **k):
        return self

    def eq(self, col, val):
        self._log.setdefault("eq", {})[col] = val
        return self

    def gte(self, col, val):
        self._log.setdefault("gte", {})[col] = val
        return self

    def lte(self, col, val):
        self._log.setdefault("lte", {})[col] = val
        return self

    def order(self, col, desc=False):
        self._log.setdefault("order", []).append((col, desc))
        return self

    def limit(self, n):
        self._log["limit"] = n
        return self

    def execute(self):
        return type("R", (), {"data": self._rows})()


class _FakeDB:
    def __init__(self, rows):
        self._rows = rows
        self.log = {}
        self.tables = []

    def table(self, name):
        self.tables.append(name)
        return _FakeQuery(self._rows, self.log)


class _NoEmbed:
    def embed_query(self, text):  # pragma: no cover - 호출되면 실패해야 함
        raise AssertionError("list_recent_news 는 임베딩을 호출하면 안 된다")


def _cluster(cid, title, first, last, sentiment, stock="005930"):
    return {
        "id": cid,
        "stock_code": stock,
        "summary_title": title,
        "event_signature": {"core_topic": title},
        "factual_body": f"{title} 본문",
        "easy_explanation": None,
        "first_published_at": first,
        "last_active_at": last,
        "sentiment_label": sentiment,
        "summary_status": "done",
    }


def _retriever(rows):
    db = _FakeDB(rows)
    return HybridRetriever(db, cfg, _NoEmbed()), db


def test_list_recent_news_no_embedding_and_filters():
    rows = [
        _cluster(2, "사건B", "2026-07-24T09:00:00+09:00", "2026-07-24T10:00:00+09:00", "negative"),
        _cluster(1, "사건A", "2026-07-24T08:00:00+09:00", "2026-07-24T08:30:00+09:00", "negative"),
    ]
    r, db = _retriever(rows)
    out = r.list_recent_news(
        stock_code="005930", date_from="2026-07-24", date_to="2026-07-24", sentiment="negative"
    )
    assert db.tables == ["news_clusters"]  # 벡터 RPC 아님
    assert db.log["eq"]["stock_code"] == "005930"
    assert db.log["eq"]["sentiment_label"] == "negative"
    assert ("last_active_at", True) in db.log["order"]  # 최신순 desc
    assert len(out) == 2
    assert all(c.source_type == "news_event" for c in out)
    assert all(c.stock_code == "005930" for c in out)  # 타 종목 혼입 없음


def test_list_recent_news_dedupes_by_cluster():
    """사건(cluster) 단위 조회이므로 동일 사건 chunk_id 중복이 없다."""
    rows = [
        _cluster(5, "사건X", "2026-07-24T09:00:00+09:00", "2026-07-24T10:00:00+09:00", "neutral"),
        _cluster(6, "사건Y", "2026-07-23T09:00:00+09:00", "2026-07-23T10:00:00+09:00", "neutral"),
    ]
    r, _ = _retriever(rows)
    out = r.list_recent_news(stock_code="005930")
    ids = [c.chunk_id for c in out]
    assert len(ids) == len(set(ids))  # 중복 없음
    assert ids == ["news_cluster:5", "news_cluster:6"]


def test_list_recent_news_empty_returns_empty_no_substitution():
    r, _ = _retriever([])
    out = r.list_recent_news(stock_code="005930", date_from="2026-07-24", date_to="2026-07-24")
    assert out == []  # 다른 종목·기간으로 대체하지 않음
