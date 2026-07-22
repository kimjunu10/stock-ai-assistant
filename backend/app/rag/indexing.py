"""뉴스 사건 인덱싱 (SPEC §8.2, Phase 2).

흐름: 활성 클러스터 조회 → 정규화 → 청킹 → passage 임베딩 → rag_documents/rag_chunks 저장.
- 해시 기반 중복 방지: 문서 content_hash 가 기존 current 와 같으면 임베딩/저장을 건너뛴다.
- 인덱싱 조건: 활성 clustering_version + summary_status='success' + factual_body + stock_code.
- 대표 기사 전체 본문은 기본 검색에 넣지 않는다.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from supabase import Client

from app.core.config import Settings
from app.ml.embeddings import UpstageEmbedder, content_hash
from app.rag.chunking import NEWS_CHUNKING_VERSION, chunk_news_event
from app.rag.normalization import build_search_text
from app.repositories.rag import RagRepository

logger = logging.getLogger("uvicorn.error.rag_indexing")

SOURCE_TYPE = "news_event"


@dataclass
class IndexResult:
    processed: int = 0
    indexed: int = 0
    skipped_unchanged: int = 0
    chunks_written: int = 0
    embedded_chunks: int = 0
    failures: int = 0
    failed_source_pks: list[str] = field(default_factory=list)


class NewsEventIndexer:
    def __init__(
        self,
        client: Client,
        cfg: Settings,
        repo: RagRepository,
        embedder: UpstageEmbedder,
    ) -> None:
        self._db = client
        self._cfg = cfg
        self._repo = repo
        self._embedder = embedder

    def _active_version(self) -> str:
        resp = (
            self._db.table("news_pipeline_state")
            .select("active_version")
            .eq("id", 1)
            .single()
            .execute()
        )
        return resp.data["active_version"]

    def _stock_names(self) -> dict[str, str]:
        resp = self._db.table("stocks").select("code,name").execute()
        return {r["code"]: r.get("name", "") for r in (resp.data or [])}

    def fetch_active_clusters(self, limit: int | None = None) -> list[dict[str, Any]]:
        """인덱싱 대상 활성 뉴스 사건을 최신순으로 조회한다.

        limit 이 None 이면 PostgREST 기본 1000행 제한을 넘겨 전 건을 페이지네이션한다.
        """

        version = self._active_version()
        fields = (
            "id,stock_code,kind,summary_title,easy_explanation,factual_body,"
            "last_active_at,first_published_at,representative_article_id"
        )

        def base():
            return (
                self._db.table("news_clusters")
                .select(fields)
                .eq("clustering_version", version)
                .eq("summary_status", "success")
                .not_.is_("factual_body", "null")
                .not_.is_("stock_code", "null")
                .order("last_active_at", desc=True)
            )

        if limit:
            return base().limit(limit).execute().data or []

        page_size = 1000
        rows: list[dict[str, Any]] = []
        for start in range(0, 1_000_000, page_size):
            batch = base().range(start, start + page_size - 1).execute().data or []
            rows.extend(batch)
            if len(batch) < page_size:
                break
        return rows

    def index_clusters(self, clusters: list[dict[str, Any]]) -> IndexResult:
        result = IndexResult()
        names = self._stock_names()

        for cluster in clusters:
            result.processed += 1
            try:
                self._index_one(cluster, names, result)
            except Exception:  # noqa: BLE001 - 개별 사건 실패는 격리, 나머지는 계속
                result.failures += 1
                result.failed_source_pks.append(str(cluster.get("id")))
                logger.exception("RAG_INDEX_CLUSTER_FAILED cluster_id=%s", cluster.get("id"))
        return result

    def _index_one(
        self, cluster: dict[str, Any], names: dict[str, str], result: IndexResult
    ) -> None:
        source_pk = str(cluster["id"])
        chunks = chunk_news_event(
            summary_title=cluster.get("summary_title"),
            easy_explanation=cluster.get("easy_explanation"),
            factual_body=cluster.get("factual_body"),
        )
        if not chunks:
            return

        # 문서 단위 content_hash = 청크 내용 결합 해시(중복 재임베딩 방지)
        doc_hash = content_hash("\n---\n".join(c.content for c in chunks))
        current = self._repo.find_current_document(SOURCE_TYPE, source_pk)
        if current and current.get("content_hash") == doc_hash:
            result.skipped_unchanged += 1
            return

        doc = self._repo.upsert_document(
            {
                "source_type": SOURCE_TYPE,
                "source_pk": source_pk,
                "stock_code": cluster.get("stock_code"),
                "title": cluster.get("summary_title"),
                "published_at": cluster.get("last_active_at"),
                "content_hash": doc_hash,
                "parser_name": "news_event",
                "parser_version": "v1",
                "chunking_version": NEWS_CHUNKING_VERSION,
                "metadata": {
                    "kind": cluster.get("kind"),
                    "first_published_at": cluster.get("first_published_at"),
                    "representative_article_id": cluster.get("representative_article_id"),
                },
            }
        )
        document_id = doc["id"]

        stock_code = cluster.get("stock_code")
        stock_name = names.get(stock_code or "", "")
        vectors = self._embedder.embed_passages([c.content for c in chunks])
        result.embedded_chunks += len(vectors)

        rows: list[dict[str, Any]] = []
        for chunk, vec in zip(chunks, vectors, strict=True):
            search_text = build_search_text(
                stock_name, stock_code, cluster.get("summary_title"), chunk.content
            )
            rows.append(
                {
                    "chunk_order": chunk.chunk_order,
                    "content": chunk.content,
                    "search_text": search_text,
                    "content_hash": content_hash(chunk.content),
                    "embedding": vec,
                    "value_kind": chunk.value_kind,
                    "token_estimate": len(chunk.content) // 2,
                    "source_locator": {
                        "cluster_id": cluster["id"],
                        "representative_article_id": cluster.get("representative_article_id"),
                    },
                    # denormalized filter 컬럼 (rag_documents 와 일치 보장)
                    "stock_code": stock_code,
                    "source_type": SOURCE_TYPE,
                    "published_at": cluster.get("last_active_at"),
                    "is_active": True,
                }
            )

        self._repo.replace_chunks(document_id, rows)
        result.indexed += 1
        result.chunks_written += len(rows)
