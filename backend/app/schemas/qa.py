"""QA 요청/응답 모델 (Phase 2)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class EventContext(BaseModel):
    """후속 질문("그 뉴스 이후 …")이 가리키는 사건의 구조화 문맥.

    직전 자연어 답변을 다시 파싱해 사건을 추측하지 않기 위한 계약이다. 값은 직전 응답의
    Tool 결과(뉴스 카드) 또는 사용자가 직접 선택한 카드에서 그대로 온다. 프런트가 답변
    텍스트에서 날짜·제목을 추출해 채우면 안 된다.
    """

    event_id: str  # 뉴스 사건/공시/리포트 출처 식별자(source_id)
    stock_code: str | None = Field(default=None, pattern=r"^[0-9]{6}$")
    # 발표 날짜 또는 발표 시각(ISO). 주가 계산 계층의 필수 입력.
    published_at: str | None = None
    title: str | None = None
    source_type: str | None = None  # news_event | dart_document | research_report 등
    # 사용자가 카드를 직접 선택했는가(자동 연결보다 항상 우선).
    user_selected: bool = False


class QaRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    stock_code: str | None = Field(default=None, pattern=r"^[0-9]{6}$")
    # 현재 보고 있는 문맥(뉴스 사건 id 등). 있으면 해당 문서를 우선한다.
    context_source_id: str | None = None
    context_source_type: str | None = None
    # 사건 후속 질문 계약(§4). 직전 응답에 사건이 정확히 1개이거나 사용자가 직접 고른
    # 경우에만 채운다. 여러 사건 중 임의 선택 금지 — 비워 보내면 백엔드가 되묻는다.
    event_context: list[EventContext] = Field(default_factory=list, max_length=10)
    selected_event_id: str | None = None
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
