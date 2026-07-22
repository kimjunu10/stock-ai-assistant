"""의미 검색 + 현재 문맥 우선 (SPEC §9, Phase 2 범위).

Phase 2 는 의미 검색(pgvector cosine)만 사용한다. 하이브리드(키워드+RRF)는 Phase 3.
현재 보고 있는 문서(context_source_id)가 있으면 그 사건 청크를 상위로 끌어올린다.
"""

from __future__ import annotations

from dataclasses import dataclass

from supabase import Client

from app.core.config import Settings
from app.ml.embeddings import UpstageEmbedder


@dataclass
class RetrievedChunk:
    chunk_id: str
    document_id: str
    content: str
    value_kind: str | None
    stock_code: str | None
    source_type: str | None
    published_at: str | None
    source_pk: str | None
    title: str | None
    publisher: str | None
    source_url: str | None
    similarity: float


class SemanticRetriever:
    def __init__(self, client: Client, cfg: Settings, embedder: UpstageEmbedder) -> None:
        self._db = client
        self._cfg = cfg
        self._embedder = embedder

    def search(
        self,
        question: str,
        *,
        stock_code: str | None = None,
        source_type: str | None = None,
        context_source_id: str | None = None,
        top_k: int | None = None,
    ) -> list[RetrievedChunk]:
        top_k = top_k or self._cfg.rag_retrieval_top_k
        query_vec = self._embedder.embed_query(question)
        if not query_vec:
            return []

        resp = self._db.rpc(
            "rag_search_semantic",
            {
                "query_embedding": query_vec,
                "match_count": self._cfg.rag_retrieval_candidate_k,
                "filter_stock_code": stock_code,
                "filter_source_type": source_type,
            },
        ).execute()
        rows = resp.data or []

        chunks = [
            RetrievedChunk(
                chunk_id=r["chunk_id"],
                document_id=r["document_id"],
                content=r["content"],
                value_kind=r.get("value_kind"),
                stock_code=r.get("stock_code"),
                source_type=r.get("source_type"),
                published_at=r.get("published_at"),
                source_pk=r.get("doc_source_pk"),
                title=r.get("doc_title"),
                publisher=r.get("doc_publisher"),
                source_url=r.get("doc_source_url"),
                similarity=r.get("similarity", 0.0),
            )
            for r in rows
        ]

        # 현재 문맥 우선: context_source_id 와 같은 사건 청크를 맨 앞으로.
        if context_source_id:
            chunks.sort(key=lambda c: c.source_pk != context_source_id)

        return chunks[:top_k]
