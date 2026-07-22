"""하이브리드 검색 중복 제거 로직 단위 테스트 (SPEC §10.5)."""

from __future__ import annotations

from unittest.mock import MagicMock

from app.core.config import Settings
from app.rag.retrieval import HybridRetriever, RetrievedChunk


def _retriever() -> HybridRetriever:
    # DB/임베더는 dedupe 에 쓰이지 않으므로 mock.
    return HybridRetriever(MagicMock(), Settings(rag_max_chunks_per_document=2), MagicMock())


def _chunk(cid, doc, evt, chash, order=0) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=cid,
        document_id=doc,
        content=f"c{cid}",
        value_kind="news_interpretation",
        stock_code="005930",
        source_type="news_event",
        published_at="2026-07-22",
        source_pk=evt,
        title="t",
        publisher="p",
        source_url="u",
        similarity=0.5,
        chunk_order=order,
        content_hash=chash,
    )


def test_dedup_drops_same_content_hash():
    r = _retriever()
    out = r._dedupe(
        [
            _chunk("1", "docA", "e1", "H"),
            _chunk("2", "docB", "e2", "H"),  # 같은 content_hash → 제거
        ]
    )
    assert len(out) == 1


def test_dedup_max_two_per_document():
    r = _retriever()
    out = r._dedupe(
        [
            _chunk("1", "docA", "e1", "h1"),
            _chunk("2", "docA", "e1", "h2"),
            _chunk("3", "docA", "e1", "h3"),  # 문서당 3번째 → 제거
        ]
    )
    assert len(out) == 2
    assert all(c.document_id == "docA" for c in out)


def test_dedup_max_two_per_event():
    r = _retriever()
    # 서로 다른 문서지만 같은 사건(source_pk) 이면 사건당 2개 제한
    out = r._dedupe(
        [
            _chunk("1", "docA", "evt", "h1"),
            _chunk("2", "docB", "evt", "h2"),
            _chunk("3", "docC", "evt", "h3"),
        ]
    )
    assert len(out) == 2


def test_dedup_keeps_distinct_events():
    r = _retriever()
    out = r._dedupe(
        [
            _chunk("1", "docA", "e1", "h1"),
            _chunk("2", "docB", "e2", "h2"),
            _chunk("3", "docC", "e3", "h3"),
        ]
    )
    assert len(out) == 3
