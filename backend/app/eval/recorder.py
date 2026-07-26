"""Tool 호출 기록용 평가 전용 middleware.

운영 응답(`AgentQaResult` / `/api/qa`)은 Tool 입력 인자와 Tool 별 지연시간을 노출하지
않는다(`AgentToolCall` 은 name·status·result_count 뿐이고 `ToolTrace.latency_ms` 는
값이 채워지지 않는다). 평가에는 둘 다 필요하므로 운영 코드를 고치는 대신
평가 실행기에서만 이 middleware 를 얹어 관찰한다.

운영 경로에는 절대 등록하지 않는다 — app/agent/runtime.py 는 이 파일을 import 하지 않는다.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any

from langchain.agents.middleware import AgentMiddleware


@dataclass
class RecordedCall:
    """Tool 호출 1건의 관찰 결과."""

    name: str
    args: dict[str, Any]
    status: str | None = None
    latency_ms: int = 0
    error: str | None = None


@dataclass
class ToolCallRecorder(AgentMiddleware):
    """Tool 이름·인자·상태·지연을 순서대로 기록한다. 결과 내용은 담지 않는다."""

    calls: list[RecordedCall] = field(default_factory=list)

    def __post_init__(self) -> None:
        super().__init__()

    def reset(self) -> None:
        self.calls = []

    def wrap_tool_call(self, request, handler):  # type: ignore[no-untyped-def]
        name = getattr(request, "tool_name", "") or request.tool_call.get("name", "")
        args = dict(request.tool_call.get("args") or {})
        started = time.perf_counter()
        rec = RecordedCall(name=name, args=args)
        self.calls.append(rec)
        try:
            result = handler(request)
        except Exception as exc:  # noqa: BLE001 - 기록만 하고 그대로 올린다
            rec.latency_ms = int((time.perf_counter() - started) * 1000)
            rec.status = "error"
            rec.error = type(exc).__name__
            raise
        rec.latency_ms = int((time.perf_counter() - started) * 1000)
        rec.status = _status_of(result)
        return result


def _status_of(result: Any) -> str | None:
    """ToolMessage content(JSON 문자열)에서 status 만 뽑는다."""
    content = getattr(result, "content", result)
    if isinstance(content, str):
        try:
            payload = json.loads(content)
        except (ValueError, TypeError):
            return None
        if isinstance(payload, dict):
            status = payload.get("status")
            return status if isinstance(status, str) else None
    return None
