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


def _inclusive_end(date_to: str | None) -> str | None:
    """종료일(YYYY-MM-DD)을 그 날 끝까지 포함하도록 보정한다.

    상대 기간(resolve_relative_date_range)은 "양 끝을 포함하는" 날짜 범위를 주는데,
    날짜만 있는 문자열은 timestamptz 로 해석될 때 그 날 00:00 이 되어 당일 자료가
    통째로 잘린다. 뉴스 청크는 대부분 실제 발행 시각을 갖고 있어(자정이 아님)
    "오늘까지" 검색이 오늘치를 하나도 못 찾는 결함이 된다.
    시각이 이미 포함된 값은 사용자가 지정한 경계이므로 그대로 둔다.
    """
    if date_to and len(date_to) == 10:
        return f"{date_to}T23:59:59+09:00"
    return date_to


def _first_topic(event_signature: object) -> str | None:
    """news_clusters.event_signature 에서 사람이 읽을 대표 주제를 뽑는다(제목 대체용)."""
    if isinstance(event_signature, dict):
        topic = event_signature.get("core_topic")
        if isinstance(topic, str) and topic.strip():
            return topic
    return None


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
                "filter_to": _inclusive_end(date_to),
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

        self._hydrate_news_cluster_metadata(final)
        if expand_parent:
            self._expand_parents(final)
        return final

    def _hydrate_news_cluster_metadata(self, chunks: list[RetrievedChunk]) -> None:
        """하이브리드 RPC에 없는 뉴스 클러스터 메타데이터를 보강한다.

        뉴스 감성은 인덱싱 이후 ``news_clusters``에 기록될 수 있으므로, 최신 뉴스
        조회와 하이브리드 검색이 같은 카드 계약을 갖도록 원본 클러스터에서 읽는다.
        감성 보강 실패가 핵심 검색 결과까지 막지는 않게 안전하게 건너뛴다.
        """
        cluster_ids = sorted(
            {
                int(chunk.source_pk)
                for chunk in chunks
                if chunk.source_type == "news_event" and str(chunk.source_pk or "").isdigit()
            }
        )
        if not cluster_ids:
            return
        try:
            rows = (
                self._db.table("news_clusters")
                .select("id,sentiment_label")
                .in_("id", cluster_ids)
                .execute()
            ).data or []
        except Exception:  # noqa: BLE001 - 선택 메타데이터 실패로 검색 자체를 막지 않는다.
            return
        sentiment_by_id = {
            int(row["id"]): row.get("sentiment_label")
            for row in rows
            if isinstance(row, dict) and str(row.get("id", "")).isdigit()
        }
        for chunk in chunks:
            if not (chunk.source_type == "news_event" and str(chunk.source_pk or "").isdigit()):
                continue
            cluster_id = int(chunk.source_pk)
            locator = dict(chunk.source_locator or {})
            locator.setdefault("cluster_id", cluster_id)
            if cluster_id in sentiment_by_id:
                locator["sentiment_label"] = sentiment_by_id[cluster_id]
            chunk.source_locator = locator

    def get_news_event(
        self,
        cluster_id: str,
        *,
        stock_code: str | None = None,
    ) -> RetrievedChunk | None:
        """Return the exact UI-selected news event without semantic recall risk."""

        if not str(cluster_id).isdigit():
            return None
        query = (
            self._db.table("news_clusters")
            .select(
                "id,stock_code,summary_title,event_signature,factual_body,"
                "easy_explanation,first_published_at,sentiment_label"
            )
            .eq("id", int(cluster_id))
        )
        if stock_code:
            query = query.eq("stock_code", stock_code)
        rows = query.limit(1).execute().data or []
        if not rows:
            return None
        row = rows[0]
        title = row.get("summary_title") or _first_topic(row.get("event_signature"))
        return RetrievedChunk(
            chunk_id=f"news_cluster:{row['id']}",
            document_id=f"news_cluster:{row['id']}",
            content=row.get("factual_body") or row.get("easy_explanation") or "",
            value_kind=None,
            stock_code=row.get("stock_code"),
            source_type="news_event",
            published_at=row.get("first_published_at"),
            source_pk=str(row["id"]),
            title=title,
            publisher=None,
            source_url=None,
            similarity=1.0,
            source_locator={
                "cluster_id": int(row["id"]),
                "sentiment_label": row.get("sentiment_label"),
            },
        )

    def list_recent_news(
        self,
        *,
        stock_code: str,
        date_from: str | None = None,
        date_to: str | None = None,
        sentiment: str | None = None,
        top_k: int | None = None,
    ) -> list[RetrievedChunk]:
        """검색 주제 없는 뉴스 조회(SPEC §10, prompt.md 2절).

        특정 사건·제품·주제가 없을 때는 의미 검색(임베딩)을 수행하지 않고,
        종목·기간·감성 조건으로 뉴스 **사건(news_clusters)** 을 최신순 조회한다.
        - 임베딩 API 를 호출하지 않는다(query 벡터 없음).
        - 사건 단위(cluster) 결과 → 동일 사건 중복 없음.
        - 최신순(last_active_at desc, 동률 시 first_published_at desc).
        - 결과 없으면 빈 리스트(다른 종목·기간 대체 금지).
        """
        top_k = top_k or self._cfg.rag_retrieval_top_k
        q = (
            self._db.table("news_clusters")
            .select(
                "id,stock_code,summary_title,event_signature,factual_body,"
                "easy_explanation,first_published_at,last_active_at,sentiment_label,"
                "summary_status"
            )
            .eq("stock_code", stock_code)
        )
        if date_from:
            q = q.gte("last_active_at", date_from)
        if date_to:
            # date_to 는 날짜(YYYY-MM-DD)일 수 있으므로 종료일 끝까지 포함.
            q = q.lte("last_active_at", _inclusive_end(date_to))
        if sentiment:
            q = q.eq("sentiment_label", sentiment)
        rows = (
            q.order("last_active_at", desc=True)
            .order("first_published_at", desc=True)
            .limit(top_k)
            .execute()
        ).data or []

        out: list[RetrievedChunk] = []
        for r in rows:
            title = r.get("summary_title") or _first_topic(r.get("event_signature"))
            body = r.get("factual_body") or r.get("easy_explanation") or ""
            out.append(
                RetrievedChunk(
                    chunk_id=f"news_cluster:{r['id']}",
                    document_id=f"news_cluster:{r['id']}",
                    content=body,
                    value_kind=None,
                    stock_code=r.get("stock_code"),
                    source_type="news_event",
                    # 기간 필터·정렬과 사용자에게 노출하는 날짜는 같은 사건 활동시각을 쓴다.
                    published_at=r.get("last_active_at"),
                    source_pk=str(r["id"]),
                    title=title,
                    publisher=None,
                    source_url=None,
                    similarity=0.0,
                    source_locator={"sentiment_label": r.get("sentiment_label")},
                )
            )
        return out

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
