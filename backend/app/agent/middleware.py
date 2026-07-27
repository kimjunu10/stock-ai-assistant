"""Agent 안전장치 middleware (Phase 5.5-C, SPEC §8).

prebuilt 로 부족한 두 가지를 커스텀 AgentMiddleware 로 보완한다:
- DuplicateToolCallMiddleware: 동일 Tool + 동일 인자 반복 호출 차단(무한/낭비 방지).
- sanitize_tool_error: ToolErrorMiddleware 에 넘길 오류 정제 콜백(내부 예외 비노출).

planner/router/classifier 가 아니다 — 실행 안전장치일 뿐이다(5.5-C 금지사항 아님).
전체 timeout 은 실행 계층(agent_qa)에서 감싼다(middleware 로 벽시계 timeout 을 강제하지 않음).
"""

from __future__ import annotations

import json
from typing import Any

from langchain.agents.middleware import AgentMiddleware
from pydantic import ValidationError

from app.agent.tools.common import (
    error,
    log_tool_exception,
    tool_runtime_log_context,
)


def sanitize_tool_error(exc: Exception) -> str:
    """ToolErrorMiddleware 콜백. 모든 예외를 표준 status=error JSON으로 반환한다."""

    log_tool_exception(exc, layer="tool_wrapper")
    public_message = (
        "Tool 입력값이 허용된 형식과 맞지 않습니다. Tool 스키마의 enum·필수 형식을 확인하세요."
        if isinstance(exc, ValidationError)
        else f"이 Tool 은 일시적 오류({type(exc).__name__})로 결과를 반환하지 못했습니다."
    )
    return json.dumps(error(public_message).model_dump_agent(), ensure_ascii=False)


def _args_key(name: str, args: dict[str, Any]) -> str:
    try:
        return name + "::" + json.dumps(args, ensure_ascii=False, sort_keys=True, default=str)
    except Exception:  # noqa: BLE001
        return name + "::" + repr(args)


class DuplicateToolCallMiddleware(AgentMiddleware):
    """동일 (Tool 이름 + 인자) 조합이 max_repeats 를 넘으면 재실행하지 않고 안내 메시지 반환.

    검색을 인자를 바꿔 1회 재시도하는 정상 흐름은 막지 않는다(인자가 다르면 다른 key).
    """

    def __init__(self, max_repeats: int = 1) -> None:
        super().__init__()
        self._max_repeats = max_repeats
        self._seen: dict[str, int] = {}

    def before_agent(self, state, runtime):  # type: ignore[override]
        # Agent 는 lru_cache 로 1회 생성돼 모든 요청이 이 인스턴스를 공유한다.
        # 요청(질문)마다 반복 카운트를 초기화해야 이전 질문의 호출이 이번 질문을
        # 막지 않는다(요청 간 상태 누수 방지).
        self._seen = {}
        return None

    def wrap_tool_call(self, request, handler):  # type: ignore[override]
        name = getattr(request, "tool_name", None) or getattr(
            getattr(request, "tool_call", {}), "get", lambda *_: None
        )("name")
        args = {}
        tc = getattr(request, "tool_call", None)
        if isinstance(tc, dict):
            name = name or tc.get("name")
            args = tc.get("args", {}) or {}
        key = _args_key(str(name), args)
        self._seen[key] = self._seen.get(key, 0) + 1
        if self._seen[key] > self._max_repeats:
            from langchain_core.messages import ToolMessage

            tool_call_id = ""
            if isinstance(tc, dict):
                tool_call_id = tc.get("id", "") or ""
            return ToolMessage(
                content=json.dumps(
                    {
                        "status": "error",
                        "warnings": [
                            "동일 Tool 을 같은 인자로 이미 호출했습니다. "
                            "다른 인자로 시도하거나 확보한 근거로 답하세요."
                        ],
                    },
                    ensure_ascii=False,
                ),
                tool_call_id=tool_call_id,
                name=str(name),
            )
        return handler(request)


class ToolRuntimeObservabilityMiddleware(AgentMiddleware):
    """요청별 Tool 이름·인자·correlation ID를 내부 예외 로그 문맥에 연결한다."""

    def wrap_tool_call(self, request, handler):  # type: ignore[override]
        tc = getattr(request, "tool_call", None)
        tc = tc if isinstance(tc, dict) else {}
        name = getattr(request, "tool_name", None) or tc.get("name") or "unknown"
        args = tc.get("args") or {}
        runtime = getattr(request, "runtime", None)
        context = getattr(runtime, "context", None)
        request_id = getattr(context, "request_id", None)
        with tool_runtime_log_context(
            tool_name=str(name),
            args=args if isinstance(args, dict) else {"raw": args},
            request_id=request_id,
        ):
            return handler(request)
