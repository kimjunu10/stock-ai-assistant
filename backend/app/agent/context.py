"""Agent 런타임 컨텍스트 (Phase 5.5-B, SPEC §5).

UI·API가 이미 아는 정보(현재 종목·문서·페이지)를 모델이 다시 추측하지 않도록 전달한다.
LangChain create_agent 의 context_schema 로 쓰며, Tool 이 ToolRuntime 을 통해 접근한다.
이 단계(5.5-B)에서는 Agent 를 아직 생성하지 않는다 — 계약 정의만 한다.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class QaRuntimeContext:
    """질문 1건의 실행 컨텍스트. 전부 선택값이며 모델이 임의 종목을 고르지 않게 한다."""

    stock_code: str | None = None
    source_type: str | None = None
    source_id: str | None = None
    document_id: str | None = None
    report_page: int | None = None
    conversation_id: str | None = None
