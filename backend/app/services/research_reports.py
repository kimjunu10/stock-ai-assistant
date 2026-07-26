"""증권사 리포트 검색 (Phase 5, search_research_reports).

기존 하이브리드 검색(HybridRetriever)을 source_type='research_report' 로 재사용한다.
RPC 가 is_active=true AND is_current=true 를 강제하므로 partial(비활성) 리포트와
NULL 임베딩 청크는 자동 제외된다.

반환 결과에 리포트 메타(제목·증권사·발행일·pdf_page/source_page·표 value_kind 요약)를
보강한다. 전망값(forecast)을 실제 실적으로 표현하지 않도록 value_kind 를 그대로 노출한다.
QA 연결·Agentic·MCP 없음. 특정 종목/증권사 하드코딩 없음.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, timedelta

from supabase import Client

from app.core.config import Settings
from app.rag.retrieval import HybridRetriever, RetrievedChunk

# 시간 문맥(prompt.md §5). Agent 가 질문 의미로 판단해 인자로 넘긴다(코드가 키워드 분류 안 함).
TIME_CONTEXTS = ("current", "historical_point", "around_event", "history")
# current 정책 기본값(설정값으로 관리; 여기 상수는 기본).
CURRENT_PRIMARY_DAYS = 90  # 최근 90일 우선
CURRENT_EXPAND_DAYS = 180  # 부족하면 180일까지 확대
CURRENT_MIN_BROKERS = 2  # 이 미만이면 확대 시도


def _norm_broker(text: str) -> str:
    """증권사명 비교용 정규화(NFC 통일 + 공백 제거). 그 이상 느슨하게 하지 않는다."""
    return re.sub(r"\s+", "", unicodedata.normalize("NFC", text))


def _to_date(s: str | None) -> date | None:
    if not s:
        return None
    try:
        return date.fromisoformat(s[:10])
    except ValueError:
        return None


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
    # 구조화 목표주가(migration 0022). status='stated' 일 때만 값이 신뢰 가능.
    target_price: int | None = None
    target_price_currency: str | None = None
    target_price_status: str = "unknown"
    target_price_effective_date: str | None = None
    target_price_source_page: int | None = None
    # 시간 문맥 검색 메타(호출부가 채움)
    is_stale: bool = False  # current 검색에서 90일 초과면 True


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
        time_context: str | None = None,
        as_of_date: str | None = None,
    ) -> list[ReportHit]:
        """리포트 본문을 하이브리드 검색하고 메타를 보강한다(prompt.md §5·§6, promptv2 §1~4).

        time_context(Agent 가 의미로 판단해 전달):
          - current: 최근 90일 우선(부족하면 180일 확대), 증권사별 최신 1건, 편중 방지,
            90일 초과분은 is_stale=True. **기본값**(None 이면 current 로 처리) — 목표주가
            질문 대다수가 '지금 값'을 원하므로 이력·타 종목 혼입을 막는 안전 기본값.
          - history: 변동추이 등 시계열 — 날짜별 개별값 유지(범위 합성 없음), 정렬만.
          - historical_point/around_event: date_from/date_to 로 시점 범위를 받아 그대로 필터.
        broker 필터는 RPC 에 없으므로 검색 후 report 메타로 후처리 필터링한다.
        """
        # promptv2 §1: Agent 가 time_context 를 생략해도 current 정책을 적용한다.
        # (질문 키워드 분기 없음 — 단순히 안전한 기본값을 준다.)
        effective_ctx = time_context if time_context in TIME_CONTEXTS else "current"
        base_k = top_k or self._cfg.rag_retrieval_top_k
        # current 는 증권사별 최신 1건을 뽑기 위해 후보를 넉넉히 가져온다.
        fetch_k = base_k * (4 if effective_ctx == "current" else (2 if broker else 1))
        chunks = self._retriever.search(
            question,
            stock_code=stock_code,
            source_type="research_report",
            date_from=date_from,
            date_to=date_to,
            top_k=fetch_k,
            expand_parent=False,
        )
        hits = self._enrich(chunks, requested_stock_code=stock_code)
        if broker:
            # DB 의 broker 는 NFD(자모 분리)로 저장된 값이 있고 모델이 넘기는 값은 NFC 라
            # 그냥 비교하면 같은 증권사도 걸러진다(운영 결함: "IBK투자증권 리포트"가
            # 0건으로 나옴). 양쪽을 NFC 로 맞춘 뒤 부분 일치를 본다.
            needle = _norm_broker(broker)
            hits = [h for h in hits if h.broker and needle in _norm_broker(h.broker)]

        if effective_ctx == "current":
            hits = self._apply_current_policy(hits, as_of_date)
        return hits[:base_k]

    def _apply_current_policy(
        self, hits: list[ReportHit], as_of_date: str | None
    ) -> list[ReportHit]:
        """current: 90일 우선(부족 시 180일), 증권사별 최신 1건, 편중 방지, 오래된 자료 표시.

        as_of_date 미지정 시 hits 의 최신 report_date 를 기준일로 삼는다(테스트 결정성).
        promptv2 §3·§4: 완전중복(같은 증권사·발행일·목표주가) 제거 후 증권사별 최신 1건.
        """
        # promptv2 §3: current 에서는 '현재 목표주가'만 신뢰한다. stated 가 아니거나
        # effective_date 가 report_date 와 다른 값(=이력표 과거값 등)은 목표주가를 강등한다.
        # 리포트 자체(전망 근거)는 유지하되 그 target_price 는 카드에 실리지 않게 한다.
        for h in hits:
            if h.target_price_status == "stated":
                eff = _to_date(h.target_price_effective_date)
                rdate = _to_date(h.report_date)
                # effective_date 가 있고 report_date 와 불일치하면 '현재값'이 아님 → 강등.
                if eff is not None and rdate is not None and eff != rdate:
                    h.target_price = None
                    h.target_price_status = "ambiguous"
                    h.target_price_currency = None
                    h.target_price_effective_date = None
                    h.target_price_source_page = None

        # promptv2 §4: 완전중복(broker+report_date+target_price) 선제거.
        deduped: list[ReportHit] = []
        seen: set[tuple] = set()
        for h in hits:
            key = (h.broker or "?", h.report_date, h.target_price)
            if key in seen:
                continue
            seen.add(key)
            deduped.append(h)
        hits = deduped

        dated = [(h, _to_date(h.report_date)) for h in hits]
        dated = [(h, d) for h, d in dated if d is not None]
        if not dated:
            return hits
        ref = _to_date(as_of_date) or max(d for _, d in dated)
        primary_cut = ref - timedelta(days=CURRENT_PRIMARY_DAYS)
        expand_cut = ref - timedelta(days=CURRENT_EXPAND_DAYS)

        def latest_per_broker(pool: list[tuple[ReportHit, date]]) -> list[ReportHit]:
            best: dict[str, tuple[ReportHit, date]] = {}
            for h, d in pool:
                b = h.broker or "?"
                if b not in best or d > best[b][1]:
                    best[b] = (h, d)
            # 증권사별 최신 1건, 발행일 desc 로 정렬(편중 방지: 증권사당 하나뿐)
            return [h for h, _ in sorted(best.values(), key=lambda z: z[1], reverse=True)]

        primary = [(h, d) for h, d in dated if d >= primary_cut]
        chosen = latest_per_broker(primary)
        if len({h.broker for h in chosen}) < CURRENT_MIN_BROKERS:
            # 90일 자료가 부족 → 180일까지 확대. 확대분은 오래된 자료로 표시.
            expanded = [(h, d) for h, d in dated if d >= expand_cut]
            chosen = latest_per_broker(expanded)
        for h in chosen:
            d = _to_date(h.report_date)
            h.is_stale = bool(d and d < primary_cut)
        return chosen

    def _enrich(
        self, chunks: list[RetrievedChunk], *, requested_stock_code: str | None = None
    ) -> list[ReportHit]:
        # source_pk(=file_hash) 집합으로 리포트 메타 일괄 조회
        file_hashes = {c.source_pk for c in chunks if c.source_pk}
        reports: dict[str, dict] = {}
        if file_hashes:
            rows = (
                self._db.table("research_reports")
                .select(
                    "id,file_hash,stock_code,title,broker,report_date,"
                    "investment_opinion,parse_status,"
                    "target_price,target_price_currency,target_price_status,"
                    "target_price_effective_date,target_price_source_page"
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

            # promptv2 §2: 종목 귀속 강제. 리포트/청크의 종목이 요청 종목과 다르면 그 리포트의
            # target_price 는 '다른 종목 값'이므로 절대 신뢰·반환하지 않는다(ambiguous 강등).
            tp = (rep or {}).get("target_price")
            tp_status = (rep or {}).get("target_price_status") or "unknown"
            tp_currency = (rep or {}).get("target_price_currency")
            tp_effective = (rep or {}).get("target_price_effective_date")
            tp_page = (rep or {}).get("target_price_source_page")
            rep_stock = (rep or {}).get("stock_code")
            chunk_stock = c.stock_code
            mismatch = requested_stock_code is not None and (
                (rep_stock is not None and rep_stock != requested_stock_code)
                or (chunk_stock is not None and chunk_stock != requested_stock_code)
            )
            if mismatch:
                tp = None
                tp_status = "ambiguous"
                tp_currency = None
                tp_effective = None
                tp_page = None

            hits.append(
                ReportHit(
                    chunk_id=c.chunk_id,
                    content=c.content,
                    stock_code=chunk_stock,
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
                    target_price=tp,
                    target_price_currency=tp_currency,
                    target_price_status=tp_status,
                    target_price_effective_date=tp_effective,
                    target_price_source_page=tp_page,
                )
            )
        return hits
