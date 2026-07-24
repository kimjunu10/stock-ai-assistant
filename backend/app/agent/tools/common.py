"""Agent Tool 공통 계약 (Phase 5.5-B, SPEC §6).

모든 read-only Tool 이 공유하는 결과·출처 형식과 헬퍼.
- ToolResult: status(ok/no_data/error) + data + sources + warnings
- SourceRef: 출처 메타데이터(source_id·type·title·page·value_kind 등)
- error sanitize: 내부 exception 메시지를 모델·사용자에게 노출하지 않는다.
- 결과 크기 제한: 1회 응답이 과도하게 커지지 않도록 자른다.

Tool 은 여기 계약만 따르고 실제 조회는 기존 Service(FactsService/HybridRetriever/
ResearchReportSearch)를 재사용한다. Tool 내부에서 LLM 답변을 생성하지 않는다.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

SourceType = Literal[
    "financial",
    "term",
    "news_event",
    "dart_document",
    "structured_disclosure",
    "research_report",
    "price",
]

# 1회 Tool 응답 크기 상한(모델 컨텍스트·비용 보호).
MAX_RESULT_ITEMS = 12
MAX_TEXT_CHARS = 1200


class SourceRef(BaseModel):
    """답변 인용에 쓸 출처 1건. locator 는 원본 재조회용 식별 정보."""

    source_id: str
    source_type: SourceType
    title: str | None = None
    publisher: str | None = None
    published_at: str | None = None  # ISO 문자열로 정규화
    page: int | None = None
    url: str | None = None
    value_kind: str | None = None
    locator: dict[str, Any] = Field(default_factory=dict)


class ToolResult(BaseModel):
    """모든 Tool 의 표준 반환. status 로 no_data 와 error 를 구분한다."""

    status: Literal["ok", "no_data", "error"]
    data: dict | list = Field(default_factory=dict)
    sources: list[SourceRef] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    def model_dump_agent(self) -> dict:
        """Agent 에게 넘길 직렬화 형태(JSON 안전)."""
        return self.model_dump(mode="json")


def ok(
    data: dict | list, sources: list[SourceRef] | None = None, warnings: list[str] | None = None
) -> ToolResult:
    return ToolResult(status="ok", data=data, sources=sources or [], warnings=warnings or [])


def no_data(reason: str, warnings: list[str] | None = None) -> ToolResult:
    """정확히 일치하는 데이터가 없음(오류 아님). 다른 기간/문서로 대체하지 않는다."""
    w = list(warnings or [])
    w.append(reason)
    return ToolResult(status="no_data", data={}, sources=[], warnings=w)


def error(public_message: str) -> ToolResult:
    """내부 예외를 감춘 안전한 오류. public_message 만 노출한다."""
    return ToolResult(status="error", data={}, sources=[], warnings=[public_message])


def sanitize_exception(exc: Exception) -> str:
    """예외를 사용자·모델에 안전한 문자열로 변환(스택·내부 메시지 비노출)."""
    return f"내부 조회 오류({type(exc).__name__})가 발생해 이 Tool 은 결과를 반환하지 못했습니다."


def iso(value: Any) -> str | None:
    """날짜/문자열을 ISO 문자열로 정규화."""
    if value is None:
        return None
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return str(value)


def clamp_text(text: str | None, limit: int = MAX_TEXT_CHARS) -> str:
    if not text:
        return ""
    t = text.strip()
    return t if len(t) <= limit else t[:limit] + "…"


def clamp_items(items: list, limit: int = MAX_RESULT_ITEMS) -> list:
    return items[:limit]
