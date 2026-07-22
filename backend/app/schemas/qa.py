"""QA 요청/응답 모델 (Phase 2)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class QaRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    stock_code: str | None = Field(default=None, pattern=r"^[0-9]{6}$")
    # 현재 보고 있는 문맥(뉴스 사건 id 등). 있으면 해당 문서를 우선한다.
    context_source_id: str | None = None
    context_source_type: str | None = None
    stream: bool = True


class Source(BaseModel):
    citation: int
    title: str | None = None
    publisher: str | None = None
    url: str | None = None
    source_type: str | None = None
    stock_code: str | None = None
    published_at: str | None = None
    chunk_id: str | None = None


class QaResponse(BaseModel):
    answer: str
    sources: list[Source]
    invalid_citations: list[int] = []
    latency_ms: dict = {}
