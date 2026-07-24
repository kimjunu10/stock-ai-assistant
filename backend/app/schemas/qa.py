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


class AgentToolCallInfo(BaseModel):
    """Agent 경로에서 호출한 Tool 요약(SPEC §13 execution.toolCalls)."""

    name: str
    status: str | None = None
    result_count: int | None = None


class AgentExecution(BaseModel):
    """Agent 실행 메타(Phase 5.5). Agent 경로에서만 채워진다."""

    agent: bool = True
    tool_calls: list[AgentToolCallInfo] = []
    model_calls: int = 0
    stop_reason: str | None = None
    # 5.5-E: 코드 검증 결과·근거 출처 식별자(내부추론·원문 본문 미포함).
    validation_errors: list[str] = []
    source_ids: list[str] = []


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
    # Phase 5.5-D: Agent 경로 실행 메타. 결정론적 경로에서는 None(기존 계약 유지).
    execution: AgentExecution | None = None
    # deprecated: 결정론적 QueryPlan 판정. Agent 전환 완료 후 제거 예정(한 릴리스 유지).
    query_plan: dict | None = None
