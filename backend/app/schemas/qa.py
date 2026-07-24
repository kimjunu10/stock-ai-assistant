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


class NumericSource(BaseModel):
    label: str
    value: int
    unit: str | None = None
    period: str | None = None
    basis: str | None = None
    value_kind: str | None = None
    source_type: str | None = None
    source_key: str | None = None


class QaResponse(BaseModel):
    answer: str
    sources: list[Source]
    # Phase 4 결정론적 경로 통합: 숫자 출처(SQL)·용어를 추가로 반환한다.
    # 순수 뉴스 질문에서는 빈 값이라 기존 클라이언트 계약을 깨지 않는다.
    numeric_sources: list[NumericSource] = []
    # Phase 5 리포트 검색 연결: 증권사 리포트 출처(전망·목표주가 질문에서만 채워짐).
    report_sources: list[dict] = []
    term: dict | None = None
    invalid_citations: list[int] = []
    latency_ms: dict = {}
