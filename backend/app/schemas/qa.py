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
    sources: list[Source]
    # Phase 4 결정론적 경로 통합: 숫자 출처(SQL)·용어를 추가로 반환한다.
    # 순수 뉴스 질문에서는 빈 값이라 기존 클라이언트 계약을 깨지 않는다.
    numeric_sources: list[NumericSource] = []
    # Phase 5 리포트 검색 연결: 증권사 리포트 출처(전망·목표주가 질문에서만 채워짐).
    report_sources: list[dict] = []
    term: dict | None = None
    invalid_citations: list[int] = []
    latency_ms: dict = {}
    # Phase 5.5-D: Agent 경로 실행 메타. Agent 경로에서 항상 채워진다.
    execution: AgentExecution | None = None
    # (제거됨) query_plan: legacy QueryPlan 판정 필드. Phase 5.5-G 에서 legacy 경로
    #   제거와 함께 삭제. Agent 경로는 이 필드를 채운 적이 없다.
    # prompt.md §8: 공식 정보와 증권사 의견 분리(비파괴 추가). 리포트 미사용 질문에선 빈 값.
    official_information: list[dict] = []
    broker_opinions: list[BrokerOpinion] = []
