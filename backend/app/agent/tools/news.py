"""search_news Tool (Phase 5.5-B, SPEC §7.3).

뉴스 사건을 기존 HybridRetriever(semantic+lexical+RRF)로 검색한다.
include/exclude_topics·sentiment 는 Tool 인자로 받아 결과 요약에 명시한다. 검색 엔진이
부정 표현을 완벽히 이해한다고 가정하지 않으며, Agent 가 최종 근거 선택에서 제외를 적용한다.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.agent.tools.common import (
    SourceRef,
    ToolResult,
    clamp_items,
    clamp_text,
    error,
    iso,
    no_data,
    ok,
    sanitize_exception,
)
from app.rag.retrieval import HybridRetriever


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
    limit: int = Field(default=5, ge=1, le=12)


def _has_topic(query: str | None) -> bool:
    """검색 주제가 실제로 있는지 판정(None·빈·공백 = 없음)."""
    return bool(query and query.strip())


def run_search_news(retriever: HybridRetriever, inp: SearchNewsInput) -> ToolResult:
    try:
        if _has_topic(inp.query):
            # 특정 주제 있음 → 기존 하이브리드(semantic + lexical + RRF) 유지.
            chunks = retriever.search(
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
            chunks = retriever.list_recent_news(
                stock_code=inp.stock_code,
                date_from=inp.date_from,
                date_to=inp.date_to,
                sentiment=inp.sentiment,
                top_k=inp.limit,
            )
    except Exception as e:  # noqa: BLE001
        return error(sanitize_exception(e))
    if not chunks:
        return no_data("해당 조건의 뉴스를 찾지 못했습니다.")

    data, sources = [], []
    for c in clamp_items(chunks, inp.limit):
        data.append(
            {
                "source_id": c.chunk_id,
                "title": c.title,
                "snippet": clamp_text(c.content),
                "published_at": iso(c.published_at),
                "publisher": c.publisher,
                "url": c.source_url,
            }
        )
        sources.append(
            SourceRef(
                source_id=c.chunk_id,
                source_type="news_event",
                title=c.title,
                publisher=c.publisher,
                published_at=iso(c.published_at),
                url=c.source_url,
                locator={"source_pk": c.source_pk, "document_id": c.document_id},
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
            },
        },
        sources=sources,
        warnings=warnings,
    )
