"""증권사 리포트 검색 (Phase 5, search_research_reports).

기존 하이브리드 검색(HybridRetriever)을 source_type='research_report' 로 재사용한다.
RPC 가 is_active=true AND is_current=true 를 강제하므로 partial(비활성) 리포트와
NULL 임베딩 청크는 자동 제외된다.

반환 결과에 리포트 메타(제목·증권사·발행일·pdf_page/source_page·표 value_kind 요약)를
보강한다. 전망값(forecast)을 실제 실적으로 표현하지 않도록 value_kind 를 그대로 노출한다.
QA 연결·Agentic·MCP 없음. 특정 종목/증권사 하드코딩 없음.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from supabase import Client

from app.core.config import Settings
from app.rag.retrieval import HybridRetriever, RetrievedChunk


@dataclass
class ReportHit:
    chunk_id: str
    content: str
    stock_code: str | None
    report_id: str | None
    title: str | None
    broker: str | None
    report_date: str | None
    investment_opinion: str | None
    page_number: int | None  # 리포트 본문 청크의 pdf page(1-index)
    pdf_page: int | None  # 0-index
    source_page: int | None  # 인쇄면(없으면 None → pdf_page fallback)
    table_value_kinds: dict = field(default_factory=dict)  # 해당 페이지 표 value_kind 집계
    similarity: float = 0.0
    rrf_score: float | None = None


class ResearchReportSearch:
    def __init__(self, client: Client, cfg: Settings, retriever: HybridRetriever) -> None:
        self._db = client
        self._cfg = cfg
        self._retriever = retriever

    def search(
        self,
        question: str,
        *,
        stock_code: str | None = None,
        broker: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        top_k: int | None = None,
    ) -> list[ReportHit]:
        """리포트 본문을 하이브리드 검색하고 메타를 보강한다.

        broker 필터는 RPC 에 없으므로 검색 후 report 메타로 후처리 필터링한다.
        """
        chunks = self._retriever.search(
            question,
            stock_code=stock_code,
            source_type="research_report",
            date_from=date_from,
            date_to=date_to,
            top_k=(top_k or self._cfg.rag_retrieval_top_k) * (2 if broker else 1),
            expand_parent=False,
        )
        hits = self._enrich(chunks)
        if broker:
            hits = [h for h in hits if h.broker and broker in h.broker]
        return hits[: (top_k or self._cfg.rag_retrieval_top_k)]

    def _enrich(self, chunks: list[RetrievedChunk]) -> list[ReportHit]:
        # source_pk(=file_hash) 집합으로 리포트 메타 일괄 조회
        file_hashes = {c.source_pk for c in chunks if c.source_pk}
        reports: dict[str, dict] = {}
        if file_hashes:
            rows = (
                self._db.table("research_reports")
                .select(
                    "id,file_hash,stock_code,title,broker,report_date,"
                    "investment_opinion,parse_status"
                )
                .in_("file_hash", list(file_hashes))
                .execute()
                .data
                or []
            )
            reports = {r["file_hash"]: r for r in rows}

        # report_id + page_number 로 페이지 메타(source_page/pdf_page) 및 표 value_kind 조회
        report_ids = {r["id"] for r in reports.values()}
        page_meta: dict[tuple[str, int], dict] = {}
        table_vk: dict[tuple[str, int], dict] = {}
        if report_ids:
            prows = (
                self._db.table("research_report_pages")
                .select("report_id,page_number,elements")
                .in_("report_id", list(report_ids))
                .execute()
                .data
                or []
            )
            for pr in prows:
                el = pr.get("elements") or {}
                page_meta[(pr["report_id"], pr["page_number"])] = {
                    "pdf_page": el.get("pdf_page"),
                    "source_page": el.get("source_page"),
                }
            trows = (
                self._db.table("research_report_tables")
                .select("report_id,page_number,value_kind")
                .in_("report_id", list(report_ids))
                .execute()
                .data
                or []
            )
            for tr in trows:
                key = (tr["report_id"], tr["page_number"])
                d = table_vk.setdefault(key, {})
                vk = tr.get("value_kind") or "unknown"
                d[vk] = d.get(vk, 0) + 1

        hits: list[ReportHit] = []
        for c in chunks:
            rep = reports.get(c.source_pk or "")
            # partial 리포트는 RPC 에서 이미 제외되지만, 방어적으로 한 번 더 거른다.
            if rep and rep.get("parse_status") != "success":
                continue
            report_id = rep["id"] if rep else None
            loc = c.source_locator or {}
            page_no = loc.get("page_number")
            pm = page_meta.get((report_id, page_no), {}) if report_id and page_no else {}
            vk = table_vk.get((report_id, page_no), {}) if report_id and page_no else {}
            hits.append(
                ReportHit(
                    chunk_id=c.chunk_id,
                    content=c.content,
                    stock_code=c.stock_code,
                    report_id=report_id,
                    title=(rep or {}).get("title") or c.title,
                    broker=(rep or {}).get("broker"),
                    report_date=(rep or {}).get("report_date"),
                    investment_opinion=(rep or {}).get("investment_opinion"),
                    page_number=page_no,
                    pdf_page=pm.get("pdf_page"),
                    source_page=pm.get("source_page"),
                    table_value_kinds=vk,
                    similarity=c.similarity,
                    rrf_score=c.rrf_score,
                )
            )
        return hits
