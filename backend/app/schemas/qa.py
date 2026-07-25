"""QA 요청/응답 모델 (Phase 2)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class QaRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    stock_code: str | None = Field(default=None, pattern=r"^[0-9]{6}$")
    # 현재 보고 있는 문맥(뉴스 사건 id 등). 있으면 해당 문서를 우선한다.
    context_source_id: str | None = None
    context_source_type: str | None = None
    document_id: str | None = None
    report_page: int | None = Field(default=None, ge=1)
    conversation_id: str | None = Field(default=None, max_length=128)
    # 서버 대화 상태는 아직 지원하지 않는다. 기존/향후 클라이언트의 optional 필드를
    # 깨지 않되 Agent prompt에는 전달하지 않는다.
    history: list[dict[str, Any]] = Field(default_factory=list, max_length=20)
    stream: bool = True


class Source(BaseModel):
    citation: int = 0
    source_id: str | None = None
    title: str | None = None
    publisher: str | None = None
    url: str | None = None
    source_type: str | None = None
    stock_code: str | None = None
    published_at: str | None = None
    page: int | None = None
    value_kind: str | None = None
    chunk_id: str | None = None
    locator: dict[str, Any] = Field(default_factory=dict)


VisualizationType = Literal[
    "news_cards",
    "price_snapshot",
    "price_line",
    "event_return",
    "broker_targets",
    "financial_series",
    "financial_comparison",
    "disclosure_metrics",
    "event_timeline",
    "term_definition",
]


class Visualization(BaseModel):
    """검증된 Tool 결과만 담는 Phase 7 공개 UI view model."""

    type: VisualizationType
    title: str
    data: dict[str, Any] = Field(default_factory=dict)
    source_ids: list[str] = Field(default_factory=list)


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
    tool_calls: list[AgentToolCallInfo] = Field(default_factory=list)
    model_calls: int = 0
    stop_reason: str | None = None
    # 5.5-E: 코드 검증 결과·근거 출처 식별자(내부추론·원문 본문 미포함).
    validation_errors: list[str] = Field(default_factory=list)
    source_ids: list[str] = Field(default_factory=list)


class BrokerOpinion(BaseModel):
    """증권사 전망 카드(prompt.md §8). 프런트가 공식 정보와 분리 표시할 수 있게 구조화."""

    broker: str | None = None
    report_date: str | None = None
    title: str | None = None
    investment_opinion: str | None = None
    # 목표주가는 구조화 target_price_status='stated' 인 경우에만 채워진다.
    target_price: int | None = None
    target_price_currency: str | None = None
    target_price_status: str = "unknown"
    summary: str | None = None  # 핵심 전망 근거(snippet 요약)
    source_id: str | None = None
    source_page: int | None = None
    is_stale: bool = False


class QaResponse(BaseModel):
    answer: str
    sources: list[Source] = Field(default_factory=list)
    # Phase 4 결정론적 경로 통합: 숫자 출처(SQL)·용어를 추가로 반환한다.
    # 순수 뉴스 질문에서는 빈 값이라 기존 클라이언트 계약을 깨지 않는다.
    numeric_sources: list[NumericSource] = Field(default_factory=list)
    # Phase 5 리포트 검색 연결: 증권사 리포트 출처(전망·목표주가 질문에서만 채워짐).
    report_sources: list[dict] = Field(default_factory=list)
    term: dict | None = None
    invalid_citations: list[int] = Field(default_factory=list)
    latency_ms: dict = Field(default_factory=dict)
    # Phase 5.5-D: Agent 경로 실행 메타. Agent 경로에서 항상 채워진다.
    execution: AgentExecution | None = None
    # (제거됨) query_plan: legacy QueryPlan 판정 필드. Phase 5.5-G 에서 legacy 경로
    #   제거와 함께 삭제. Agent 경로는 이 필드를 채운 적이 없다.
    # prompt.md §8: 공식 정보와 증권사 의견 분리(비파괴 추가). 리포트 미사용 질문에선 빈 값.
    official_information: list[dict] = Field(default_factory=list)
    broker_opinions: list[BrokerOpinion] = Field(default_factory=list)
    # Phase 7: ToolResult의 공개 가능한 구조화 값만 담는다. 기존 클라이언트에 비파괴적.
    visualizations: list[Visualization] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
