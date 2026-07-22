"""RAG 문서/섹션/청크/용어/리포트/운영로그 저장소 (SPEC §6).

기존 프로젝트 패턴(Supabase Python 클라이언트, service_role)을 따른다.

핵심 정책:
- 문서 버전 관리: 같은 (source_type, source_pk)에서 is_current=true 는 하나만.
  새 버전을 넣기 전에 이전 버전을 is_current=false 로 내린다(deactivate).
- 임베딩 차원/모델 세대가 다른 벡터를 섞지 않는다(Phase 0 고정 원칙).
- 원본 삭제가 검색 문서로 전파되지 않도록 원본 테이블에 FK 를 걸지 않는다.

임베딩 생성 자체는 app/ml/embeddings.py(Phase 2)에서 담당한다. 여기서는
전달받은 벡터를 저장/조회만 한다.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any, TypeVar

from supabase import Client

from app.core.config import Settings

T = TypeVar("T")

EMBEDDING_MODEL = "solar-embedding-2-passage"
EMBEDDING_DIMENSION = 1024


def _batched(items: list[T], size: int) -> Iterable[list[T]]:
    for start in range(0, len(items), size):
        yield items[start : start + size]


class RagRepository:
    """RAG 인덱싱/검색 데이터 저장소."""

    def __init__(self, client: Client, cfg: Settings) -> None:
        self._db = client
        self._cfg = cfg

    def _fetch_all(self, build_query) -> list[dict[str, Any]]:
        """Supabase 기본 1,000행 제한을 넘겨 전 행을 읽는다."""

        page_size = 1000
        rows: list[dict[str, Any]] = []
        for start in range(0, 1_000_000, page_size):
            batch = build_query(start, start + page_size - 1).execute().data or []
            rows.extend(batch)
            if len(batch) < page_size:
                break
        return rows

    # -- documents --------------------------------------------------------
    def deactivate_previous_versions(self, source_type: str, source_pk: str) -> int:
        """같은 원본의 기존 is_current 문서를 모두 비활성화한다.

        새 버전 upsert 전에 호출해 is_current unique 부분 인덱스 충돌을 막는다.
        반환: 비활성화된 문서 수.
        """

        resp = (
            self._db.table("rag_documents")
            .update({"is_current": False})
            .eq("source_type", source_type)
            .eq("source_pk", source_pk)
            .eq("is_current", True)
            .execute()
        )
        return len(resp.data or [])

    def find_current_document(self, source_type: str, source_pk: str) -> dict[str, Any] | None:
        resp = (
            self._db.table("rag_documents")
            .select("*")
            .eq("source_type", source_type)
            .eq("source_pk", source_pk)
            .eq("is_current", True)
            .limit(1)
            .execute()
        )
        rows = resp.data or []
        return rows[0] if rows else None

    def upsert_document(
        self, doc: dict[str, Any], *, deactivate_old: bool = True
    ) -> dict[str, Any]:
        """문서 버전을 저장한다.

        - content_hash 가 기존 current 와 같으면 그대로 재사용(중복 임베딩 방지의 문서 단위 근거).
        - 내용이 바뀌었으면 기존 버전을 내리고 새 버전을 삽입한다.
        """

        source_type = doc["source_type"]
        source_pk = doc["source_pk"]
        content_hash = doc["content_hash"]

        current = self.find_current_document(source_type, source_pk)
        if current and current.get("content_hash") == content_hash:
            return current  # 동일 내용 → 재사용

        if deactivate_old:
            self.deactivate_previous_versions(source_type, source_pk)

        payload = {**doc, "is_current": True}
        payload.setdefault("embedding_model", EMBEDDING_MODEL)
        payload.setdefault("embedding_dimension", EMBEDDING_DIMENSION)
        resp = (
            self._db.table("rag_documents")
            .upsert(payload, on_conflict="source_type,source_pk,content_hash")
            .execute()
        )
        return (resp.data or [payload])[0]

    # -- sections ---------------------------------------------------------
    def replace_sections(self, document_id: str, sections: list[dict[str, Any]]) -> int:
        """문서의 섹션을 통째로 교체한다(재인덱싱 안전)."""

        self._db.table("rag_sections").delete().eq("document_id", document_id).execute()
        if not sections:
            return 0
        rows = [{**s, "document_id": document_id} for s in sections]
        total = 0
        for batch in _batched(rows, self._cfg.supabase_batch_size):
            self._db.table("rag_sections").insert(batch).execute()
            total += len(batch)
        return total

    # -- chunks -----------------------------------------------------------
    def replace_chunks(self, document_id: str, chunks: list[dict[str, Any]]) -> int:
        """문서의 청크를 통째로 교체한다. 각 청크는 embedding 과 denorm 필드를 포함한다."""

        self._db.table("rag_chunks").delete().eq("document_id", document_id).execute()
        if not chunks:
            return 0
        rows = [{**c, "document_id": document_id} for c in chunks]
        total = 0
        for batch in _batched(rows, self._cfg.supabase_batch_size):
            self._db.table("rag_chunks").insert(batch).execute()
            total += len(batch)
        return total

    def existing_chunk_hashes(self, document_id: str) -> set[str]:
        """이미 저장된 청크의 content_hash 집합(중복 임베딩 방지용)."""

        rows = self._fetch_all(
            lambda start, end: (
                self._db.table("rag_chunks")
                .select("content_hash")
                .eq("document_id", document_id)
                .range(start, end)
            )
        )
        return {r["content_hash"] for r in rows if r.get("content_hash")}

    # -- terms ------------------------------------------------------------
    def upsert_terms(self, terms: list[dict[str, Any]]) -> int:
        if not terms:
            return 0
        total = 0
        for batch in _batched(terms, self._cfg.supabase_batch_size):
            self._db.table("rag_terms").upsert(batch, on_conflict="term").execute()
            total += len(batch)
        return total

    # -- research reports -------------------------------------------------
    def find_report_by_hash(self, file_hash: str) -> dict[str, Any] | None:
        resp = (
            self._db.table("research_reports")
            .select("*")
            .eq("file_hash", file_hash)
            .limit(1)
            .execute()
        )
        rows = resp.data or []
        return rows[0] if rows else None

    def upsert_report(self, report: dict[str, Any]) -> dict[str, Any]:
        """file_hash 기준 멱등 저장(중복 업로드 방지)."""

        resp = self._db.table("research_reports").upsert(report, on_conflict="file_hash").execute()
        return (resp.data or [report])[0]

    def replace_report_pages(self, report_id: str, pages: list[dict[str, Any]]) -> int:
        self._db.table("research_report_pages").delete().eq("report_id", report_id).execute()
        if not pages:
            return 0
        rows = [{**p, "report_id": report_id} for p in pages]
        total = 0
        for batch in _batched(rows, self._cfg.supabase_batch_size):
            self._db.table("research_report_pages").insert(batch).execute()
            total += len(batch)
        return total

    def replace_report_tables(self, report_id: str, tables: list[dict[str, Any]]) -> int:
        self._db.table("research_report_tables").delete().eq("report_id", report_id).execute()
        if not tables:
            return 0
        rows = [{**t, "report_id": report_id} for t in tables]
        total = 0
        for batch in _batched(rows, self._cfg.supabase_batch_size):
            self._db.table("research_report_tables").insert(batch).execute()
            total += len(batch)
        return total

    # -- ingestion runs ---------------------------------------------------
    def start_ingestion_run(self, source_type: str, config: dict[str, Any] | None = None) -> str:
        resp = (
            self._db.table("rag_ingestion_runs")
            .insert({"source_type": source_type, "status": "running", "config": config or {}})
            .execute()
        )
        return resp.data[0]["id"]

    def finish_ingestion_run(self, run_id: str, **fields: Any) -> None:
        self._db.table("rag_ingestion_runs").update(fields).eq("id", run_id).execute()
