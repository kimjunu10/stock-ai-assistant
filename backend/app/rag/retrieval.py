"""검색 (SPEC §10).

- Phase 2: 의미 검색 단독 (SemanticRetriever) — 비교 기준으로 유지.
- Phase 3: 하이브리드 검색 (HybridRetriever) = 의미 + 키워드(pg_trgm) RRF 결합
  + 현재 문서 우선 + 중복 제거 + 부모 문맥 확장.
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
    # Phase 3 추가 필드(하이브리드/중복제거/부모문맥용)
    section_id: str | None = None
    chunk_order: int | None = None
    content_hash: str | None = None
    lexical_similarity: float | None = None
    rrf_score: float | None = None
    parent_context: str | None = None
    source_locator: dict | None = None


def _row_to_chunk(r: dict) -> RetrievedChunk:
    return RetrievedChunk(
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
        similarity=r.get("similarity") or 0.0,
        section_id=r.get("section_id"),
        chunk_order=r.get("chunk_order"),
        content_hash=r.get("content_hash"),
        lexical_similarity=r.get("lexical_similarity"),
        rrf_score=r.get("rrf_score"),
        source_locator=r.get("source_locator"),
    )


class SemanticRetriever:
    """Phase 2 의미 검색 단독. 하이브리드 비교의 기준선으로 유지한다."""

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
                "match_count": self._cfg.rag_semantic_candidates,
                "filter_stock_code": stock_code,
                "filter_source_type": source_type,
            },
        ).execute()
        chunks = [_row_to_chunk(r) for r in (resp.data or [])]

        if context_source_id:
            chunks.sort(key=lambda c: c.source_pk != context_source_id)
        return chunks[:top_k]


class HybridRetriever:
    """Phase 3 하이브리드 검색 (SPEC §10)."""

    def __init__(self, client: Client, cfg: Settings, embedder: UpstageEmbedder) -> None:
        self._db = client
        self._cfg = cfg
        self._embedder = embedder

    def _rpc(
        self,
        query_vec: list[float],
        query_text: str,
        *,
        match_count: int,
        stock_code: str | None,
        source_type: str | None,
        date_from: str | None,
        date_to: str | None,
        value_kind: str | None,
    ) -> list[RetrievedChunk]:
        resp = self._db.rpc(
            "rag_search_hybrid",
            {
                "query_embedding": query_vec,
                "query_text": query_text,
                "match_count": match_count,
                "semantic_candidates": self._cfg.rag_semantic_candidates,
                "lexical_candidates": self._cfg.rag_lexical_candidates,
                "rrf_k": self._cfg.rag_rrf_k,
                "filter_stock_code": stock_code,
                "filter_source_type": source_type,
                "filter_from": date_from,
                "filter_to": date_to,
                "filter_value_kind": value_kind,
            },
        ).execute()
        return [_row_to_chunk(r) for r in (resp.data or [])]

    def search(
        self,
        question: str,
        *,
        stock_code: str | None = None,
        source_type: str | None = None,
        context_source_id: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        value_kind: str | None = None,
        top_k: int | None = None,
        expand_parent: bool = True,
    ) -> list[RetrievedChunk]:
        top_k = top_k or self._cfg.rag_retrieval_top_k
        query_vec = self._embedder.embed_query(question)
        if not query_vec:
            return []
        query_text = question.lower()

        kwargs = {
            "stock_code": stock_code,
            "source_type": source_type,
            "date_from": date_from,
            "date_to": date_to,
            "value_kind": value_kind,
        }

        # SPEC §10.4 현재 문서 우선: 현재 문서 내부 후보 + 전체 후보를 합친다.
        candidates: list[RetrievedChunk] = []
        if context_source_id:
            in_doc = self._rpc(
                query_vec,
                query_text,
                match_count=self._cfg.rag_current_doc_candidates,
                **kwargs,
            )
            in_doc = [c for c in in_doc if c.source_pk == context_source_id]
            candidates.extend(in_doc)

        global_hits = self._rpc(
            query_vec,
            query_text,
            match_count=max(self._cfg.rag_global_candidates, top_k * 3),
            **kwargs,
        )
        candidates.extend(global_hits)

        deduped = self._dedupe(candidates)
        # 현재 문서 청크를 앞으로
        if context_source_id:
            deduped.sort(key=lambda c: c.source_pk != context_source_id)
        final = deduped[:top_k]

        if expand_parent:
            self._expand_parents(final)
        return final

    def _dedupe(self, chunks: list[RetrievedChunk]) -> list[RetrievedChunk]:
        """SPEC §10.5: content_hash 제거, 문서/사건당 최대 N, 매우 유사 청크 하나만.

        입력은 RRF 순으로 정렬돼 있다고 가정하지 않고, 안정적으로 처리한다.
        (RPC 결과가 이미 rrf_score desc; 현재문서 후보가 앞에 붙을 수 있다)
        """
        max_per_doc = self._cfg.rag_max_chunks_per_document
        seen_hash: set[str] = set()
        per_doc: dict[str, int] = {}
        per_event: dict[str, int] = {}
        out: list[RetrievedChunk] = []
        for c in chunks:
            if c.content_hash and c.content_hash in seen_hash:
                continue
            doc_key = c.document_id
            event_key = c.source_pk or c.document_id
            if per_doc.get(doc_key, 0) >= max_per_doc:
                continue
            if per_event.get(event_key, 0) >= max_per_doc:
                continue
            if c.content_hash:
                seen_hash.add(c.content_hash)
            per_doc[doc_key] = per_doc.get(doc_key, 0) + 1
            per_event[event_key] = per_event.get(event_key, 0) + 1
            out.append(c)
        return out

    def _expand_parents(self, chunks: list[RetrievedChunk]) -> None:
        """SPEC §10.7: 부모 문맥 확장.

        뉴스 사건은 section 이 없으므로 같은 문서의 앞뒤 청크를 붙인다.
        전체 문맥은 rag_context_char_budget 이하로 제한한다.
        """
        budget = self._cfg.rag_context_char_budget
        used = sum(len(c.content) for c in chunks)
        for c in chunks:
            if used >= budget or c.chunk_order is None:
                break
            neighbors = (
                self._db.table("rag_chunks")
                .select("chunk_order,content")
                .eq("document_id", c.document_id)
                .in_("chunk_order", [c.chunk_order - 1, c.chunk_order + 1])
                .execute()
            ).data or []
            extra_parts = []
            for n in sorted(neighbors, key=lambda x: x["chunk_order"]):
                piece = n["content"]
                if used + len(piece) > budget:
                    continue
                extra_parts.append(piece)
                used += len(piece)
            if extra_parts:
                c.parent_context = "\n\n".join(extra_parts)
