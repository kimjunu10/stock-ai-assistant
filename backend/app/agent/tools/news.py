"""search_news Tool (Phase 5.5-B, SPEC §7.3).

뉴스 사건을 기존 HybridRetriever(semantic+lexical+RRF)로 검색한다.
include/exclude_topics·sentiment 는 Tool 인자로 받아 결과 요약에 명시한다. 검색 엔진이
부정 표현을 완벽히 이해한다고 가정하지 않으며, Agent 가 최종 근거 선택에서 제외를 적용한다.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.agent.tools.common import (
    SourceRef,
    ToolResult,
    clamp_items,
    clamp_text,
    error,
    iso,
    log_tool_exception,
    no_data,
    ok,
    sanitize_exception,
)
from app.rag.retrieval import HybridRetriever
from app.services.relevance import classify_stock_relevance

NewsSearchPurpose = Literal["general", "price_driver"]


class SearchNewsInput(BaseModel):
    stock_code: str = Field(pattern=r"^[0-9]{6}$")
    # query 는 특정 사건·제품·주제가 있을 때만 채운다. 없으면 생략(None)한다.
    # None·빈 문자열·공백은 모두 "별도 검색 주제 없음"으로 처리한다.
    query: str | None = None
    date_from: str | None = None
    date_to: str | None = None
    sentiment: str | None = None  # positive | neutral | negative (감성 조건)
    include_topics: list[str] = Field(default_factory=list)
    exclude_topics: list[str] = Field(default_factory=list)
    current_event_id: str | None = None
    # 현재 화면의 기사 자체를 묻는 질문이면 관련 뉴스 확장을 금지한다.
    context_only: bool = False
    purpose: NewsSearchPurpose = "general"
    limit: int = Field(default=5, ge=1, le=12)


def _has_topic(query: str | None) -> bool:
    """검색 주제가 실제로 있는지 판정(None·빈·공백 = 없음)."""
    return bool(query and query.strip())


def _direct_title_match(chunk, stock_code: str) -> bool:
    decision = classify_stock_relevance(
        stock_code=stock_code,
        title=chunk.title,
        body=None,
        description=None,
    )
    return decision.relevance == "relevant"


def run_search_news(retriever: HybridRetriever, inp: SearchNewsInput) -> ToolResult:
    try:
        current_chunks = []
        if inp.current_event_id:
            current = retriever.get_news_event(
                inp.current_event_id,
                stock_code=inp.stock_code,
            )
            if current is not None:
                current_chunks.append(current)
        if inp.context_only and current_chunks:
            related_chunks = []
        elif _has_topic(inp.query):
            # 특정 주제 있음 → 기존 하이브리드(semantic + lexical + RRF) 유지.
            related_chunks = retriever.search(
                inp.query,
                stock_code=inp.stock_code,
                source_type="news_event",
                context_source_id=inp.current_event_id,
                date_from=inp.date_from,
                date_to=inp.date_to,
                top_k=inp.limit,
            )
        else:
            # 주제 없음 → 임베딩 호출 없이 종목·기간·감성 조건으로 사건 최신순 조회.
            related_chunks = retriever.list_recent_news(
                stock_code=inp.stock_code,
                date_from=inp.date_from,
                date_to=inp.date_to,
                sentiment=inp.sentiment,
                top_k=inp.limit,
            )
        chunks = current_chunks + [
            chunk for chunk in related_chunks if chunk.source_pk != inp.current_event_id
        ]
    except Exception as e:  # noqa: BLE001
        log_tool_exception(e, layer="HybridRetriever.search_news")
        return error(sanitize_exception(e))
    if inp.purpose == "price_driver":
        # 주가 원인 후보는 제목부터 해당 기업을 직접 식별하는 사건만 남긴다. 본문 어딘가에
        # 종목명이 한 번 등장한 일반 소비자 기사까지 "악재"로 노출되는 것을 막는다.
        chunks = [chunk for chunk in chunks if _direct_title_match(chunk, inp.stock_code)]
    elif inp.sentiment in {"positive", "negative"}:
        # 호재/악재 목록은 직접 관련 기사가 하나라도 있으면 그것만 사용한다. 직접 기사가
        # 전혀 없는 경우에는 산업·정책 같은 간접 영향을 놓치지 않도록 원래 결과를 유지한다.
        direct_chunks = [chunk for chunk in chunks if _direct_title_match(chunk, inp.stock_code)]
        if direct_chunks:
            chunks = direct_chunks
    if not chunks:
        return no_data("해당 조건의 뉴스를 찾지 못했습니다.")

    data, sources = [], []
    for c in clamp_items(chunks, inp.limit):
        # 감성(호재/악재/중립)은 두 검색 경로 모두 news_clusters.sentiment_label에서
        # 가져온다. Tool·Agent 는 감성을 새로 판정하지 않는다.
        locator = c.source_locator if isinstance(c.source_locator, dict) else {}
        cluster_id = str(locator.get("cluster_id") or c.source_pk or "").strip()
        cluster_url = f"/news?cluster={cluster_id}" if cluster_id.isdigit() else None
        data.append(
            {
                "source_id": c.chunk_id,
                # 다음 Tool 이 이 사건을 정확히 다시 조회할 때 쓰는 불투명 참조다.
                # 날짜는 모델이 복사하지 않고, 서버가 이 ID로 원문을 다시 조회한다.
                "event_ref": (
                    {
                        "source_type": "news_event",
                        "source_id": cluster_id,
                        "stock_code": c.stock_code,
                    }
                    if cluster_id.isdigit()
                    else None
                ),
                "title": c.title,
                "snippet": clamp_text(c.content),
                "published_at": iso(c.published_at),
                "publisher": c.publisher,
                # RAG 결과 클릭은 외부 검색이 아니라 서비스의 사건 클러스터 상세로 이동한다.
                "url": cluster_url,
                "stock_code": c.stock_code,
                "sentiment": locator.get("sentiment_label"),
            }
        )
        sources.append(
            SourceRef(
                source_id=c.chunk_id,
                source_type="news_event",
                stock_code=c.stock_code,
                title=c.title,
                publisher=c.publisher,
                published_at=iso(c.published_at),
                url=cluster_url,
                locator={
                    "source_pk": c.source_pk,
                    "cluster_id": int(cluster_id) if cluster_id.isdigit() else None,
                    "document_id": c.document_id,
                    "original_url": c.source_url,
                },
            )
        )
    warnings = []
    if inp.exclude_topics:
        warnings.append(
            f"제외 요청 주제: {inp.exclude_topics}. 이 주제에 해당하는 근거는 답변에서 제외할 것."
        )
    if inp.include_topics:
        warnings.append(f"포함 요청 주제: {inp.include_topics}.")
    return ok(
        {
            "news": data,
            "applied_filters": {
                "include_topics": inp.include_topics,
                "exclude_topics": inp.exclude_topics,
                "date_from": inp.date_from,
                "date_to": inp.date_to,
                "sentiment": inp.sentiment,
                "mode": "hybrid_search" if _has_topic(inp.query) else "recent_events",
                "purpose": inp.purpose,
            },
        },
        sources=sources,
        warnings=warnings,
    )
