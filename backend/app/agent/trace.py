"""Agent 실행 trace (Phase 5.5-E, SPEC §15).

기록: request_id, tool_calls(이름·상태·latency·result_count), model_calls, source_ids,
stop_reason, validation_errors, total_latency.

금지(미기록): 비밀키, DB 접속정보, 모델 내부 추론 전문, 전체 비공개 PDF 본문.
Tool 결과는 메타데이터·짧은 근거만. LangSmith 미사용 시 rag_query_logs 로 동일 지표 저장 가능.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass
class ToolTrace:
    name: str
    status: str | None = None
    latency_ms: int | None = None
    result_count: int | None = None


@dataclass
class AgentTrace:
    request_id: str
    model_calls: int = 0
    tool_calls: list[ToolTrace] = field(default_factory=list)
    source_ids: list[str] = field(default_factory=list)
    stop_reason: str = "completed"
    validation_errors: list[str] = field(default_factory=list)
    total_latency_ms: int | None = None

    def to_log_dict(self) -> dict:
        """rag_query_logs·로그용 안전 dict. 비밀정보·원문 본문은 담지 않는다."""
        d = asdict(self)
        # source_ids 는 식별자만(본문 아님). tool_calls 는 이름·상태·지연만.
        return d
