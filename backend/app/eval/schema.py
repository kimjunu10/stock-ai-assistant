"""Phase 8 평가 케이스 스키마.

기존 `docs/rag/phase_5_5/eval/devset.json` 의 필드(id/type/question/stock_code/
required_tools/required_tools_any/forbidden_tools/expected_args/expected_financial/
is_answerable)를 그대로 승계하고, Phase 8 이 요구하는 라벨 항목을 추가한다.

기존 필드를 이름 변경하지 않는다 — 기존 27문항(devset 17 + holdout 10)을 그대로 읽을 수
있어야 하기 때문이다. 추가 필드는 전부 선택이며 기본값이 있다.
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

# 질문 유형 — RAG_EVALUATION_PLAN.md §3 의 9개 분류를 그대로 쓴다.
QuestionType = Literal[
    "금융용어",
    "정확한 재무 숫자",
    "뉴스 사건·영향",
    "공시 설명·구조화 값",
    "증권사 리포트",
    "복수 기능 혼합",
    "부정·제외·대조",
    "현재 화면 문맥",
    "답변 불가능·모호",
]

# RAG_EVALUATION_PLAN.md §3 목표 분포.
TYPE_QUOTA: dict[str, int] = {
    "금융용어": 15,
    "정확한 재무 숫자": 25,
    "뉴스 사건·영향": 25,
    "공시 설명·구조화 값": 20,
    "증권사 리포트": 20,
    "복수 기능 혼합": 20,
    "부정·제외·대조": 15,
    "현재 화면 문맥": 10,
    "답변 불가능·모호": 10,
}

# 실제 등록된 Tool 8개(app/agent/runtime.py build_tools 와 일치해야 한다).
KNOWN_TOOLS = frozenset(
    {
        "get_financial_facts",
        "lookup_financial_term",
        "search_news",
        "search_disclosures",
        "get_disclosure_values",
        "search_research_reports",
        "get_stock_prices",
        "calculate_event_return",
    }
)

# 출처 종류 — app/agent/tools/common.py SourceType 과 일치.
SOURCE_TYPES = frozenset(
    {
        "financial",
        "term",
        "news_event",
        "dart_document",
        "structured_disclosure",
        "research_report",
        "price",
    }
)

ReviewStatus = Literal["confirmed", "needs_manual_review"]


class ScreenContext(BaseModel):
    """질문이 던져진 화면·요청 문맥(§3 '화면 또는 요청 문맥').

    실제 QaRequest 필드명과 동일하게 둬서 실행기가 그대로 전달할 수 있게 한다.
    """

    stock_code: str | None = Field(default=None, pattern=r"^[0-9]{6}$")
    context_source_type: str | None = None
    context_source_id: str | None = None
    document_id: str | None = None
    report_page: int | None = Field(default=None, ge=1)
    selected_event_id: str | None = None


class ExpectedFinancial(BaseModel):
    """재무 정답 조회 명세. 값을 직접 적지 않고 DB 기준행을 지정한다.

    정답 숫자를 사람이 옮겨 적으면 오타가 정답이 된다. 실행기가 이 명세로
    FactsService 를 조회해 기준값을 만든다(RAG 답변을 정답으로 쓰지 않음).
    """

    stock_code: str = Field(pattern=r"^[0-9]{6}$")
    account_name: str
    business_year: str | None = None
    report_period: str | None = None
    amount_type: str | None = None
    fs_div: str = "CFS"
    value_kind: str = "actual"  # actual | forecast


class ExpectedNumber(BaseModel):
    """정확히 일치해야 하는 숫자 1건(§3 '정확히 일치해야 하는 숫자', '단위')."""

    label: str
    value: float
    unit: str  # 원, %, 배, 주, 건 등
    value_kind: Literal["actual", "forecast"] = "actual"
    tolerance: float = 0.0  # 0 이면 완전 일치


class ExpectedPeriod(BaseModel):
    """기간과 실제 거래일(§3 '기간과 실제 거래일')."""

    business_year: str | None = None
    report_period: str | None = None
    amount_type: str | None = None
    start_trading_day: str | None = None  # YYYY-MM-DD, 실제 거래일
    end_trading_day: str | None = None
    event_date: str | None = None


class GoldSource(BaseModel):
    """정답 근거 1건(§3 '정답 문서·뉴스 사건·리포트·공시 식별자').

    source_id 규칙이 종류마다 달라(uuid / 접수번호 / `price:...` / 슬래시 경로)
    종류를 함께 적고, 유효성 검사는 종류별로 다르게 한다.
    """

    source_type: str
    source_id: str | None = None  # uuid·접수번호 등 확정 식별자
    ref: str | None = None  # 사람이 읽는 참조(리포트 제목, 클러스터 제목 등)
    page: int | None = Field(default=None, ge=1)
    note: str | None = None

    @field_validator("source_type")
    @classmethod
    def _known_source_type(cls, v: str) -> str:
        if v not in SOURCE_TYPES:
            raise ValueError(f"알 수 없는 출처 종류: {v}")
        return v


class EvalCase(BaseModel):
    """평가 질문 1건 + 정답 라벨."""

    model_config = {"extra": "forbid"}

    # --- 기존 devset.json 승계 필드 ---
    id: str
    type: QuestionType
    question: str = Field(min_length=1)
    stock_code: str | None = Field(default=None, pattern=r"^[0-9]{6}$")
    required_tools: list[str] = Field(default_factory=list)
    required_tools_any: list[str] = Field(default_factory=list)
    forbidden_tools: list[str] = Field(default_factory=list)
    expected_args: dict[str, dict[str, Any]] = Field(default_factory=dict)
    expected_financial: ExpectedFinancial | None = None
    # 질문이 객관적으로 두 해석을 허용할 때만 쓴다(예: "3분기 영업이익" = 누적 | 3개월치).
    # 점수를 올리려고 추가하지 않는다 — 두 해석 모두 DB 에 실재해야 하고 근거를 남긴다.
    acceptable_financials: list[ExpectedFinancial] = Field(default_factory=list)
    is_answerable: bool = True

    # --- Phase 8 추가 라벨 ---
    context: ScreenContext = Field(default_factory=ScreenContext)
    optional_tools: list[str] = Field(default_factory=list)
    gold_sources: list[GoldSource] = Field(default_factory=list)
    expected_facts: list[str] = Field(default_factory=list)
    expected_numbers: list[ExpectedNumber] = Field(default_factory=list)
    expected_period: ExpectedPeriod | None = None
    allowed_source_types: list[str] = Field(default_factory=list)
    forbidden_claims: list[str] = Field(default_factory=list)
    no_data_expectation: str | None = None
    review_status: ReviewStatus = "needs_manual_review"
    label_basis: str = ""
    split: Literal["dev", "holdout"] = "dev"
    _note: str | None = None

    @field_validator("required_tools", "required_tools_any", "forbidden_tools", "optional_tools")
    @classmethod
    def _known_tools(cls, v: list[str]) -> list[str]:
        unknown = set(v) - KNOWN_TOOLS
        if unknown:
            raise ValueError(f"등록되지 않은 Tool: {sorted(unknown)}")
        return v

    @field_validator("allowed_source_types")
    @classmethod
    def _known_source_types(cls, v: list[str]) -> list[str]:
        unknown = set(v) - SOURCE_TYPES
        if unknown:
            raise ValueError(f"알 수 없는 출처 종류: {sorted(unknown)}")
        return v

    @field_validator("expected_args")
    @classmethod
    def _args_for_known_tools(cls, v: dict[str, dict]) -> dict[str, dict]:
        unknown = set(v) - KNOWN_TOOLS
        if unknown:
            raise ValueError(f"등록되지 않은 Tool 의 기대 인자: {sorted(unknown)}")
        return v

    @model_validator(mode="after")
    def _consistency(self) -> EvalCase:
        overlap = set(self.required_tools) & set(self.forbidden_tools)
        if overlap:
            raise ValueError(f"필수·금지 Tool 이 겹침: {sorted(overlap)}")
        overlap2 = set(self.required_tools_any) & set(self.forbidden_tools)
        if overlap2:
            raise ValueError(f"택1 필수·금지 Tool 이 겹침: {sorted(overlap2)}")
        # 답변 불가능 질문은 기대 행동을 반드시 적는다(무엇을 통과로 볼지 없으면 채점 불가).
        if not self.is_answerable and not self.no_data_expectation:
            raise ValueError("답변 불가능 질문은 no_data_expectation 이 필요하다")
        # 확정 라벨은 근거를 적는다.
        if self.review_status == "confirmed" and not self.label_basis:
            raise ValueError("confirmed 라벨은 label_basis 가 필요하다")
        # 화면 문맥 유형은 문맥이 실제로 있어야 한다.
        if self.type == "현재 화면 문맥" and not (
            self.context.stock_code or self.context.context_source_id or self.context.document_id
        ):
            raise ValueError("현재 화면 문맥 유형은 context 가 비어 있을 수 없다")
        return self


class EvalSuite(BaseModel):
    """평가셋 파일 1개."""

    model_config = {"extra": "forbid"}

    note: str = ""
    cases: list[EvalCase]

    @model_validator(mode="after")
    def _unique_ids(self) -> EvalSuite:
        counts = Counter(c.id for c in self.cases)
        dup = sorted(i for i, n in counts.items() if n > 1)
        if dup:
            raise ValueError(f"중복 id: {dup}")
        return self
