"""Phase 5.5-C Agent 구현 단위 테스트 (LLM 실호출 없음).

- Tool 6개 등록·이름 확인
- create_agent 조립 성공(더미 키, invoke 안 함)
- DuplicateToolCallMiddleware: 동일 Tool+인자 반복 차단, 다른 인자는 허용
- sanitize_tool_error: 내부 예외 비노출
- AgentQaService: timeout/에러 시 안전 응답, 내부추론 미저장(fake agent)
- feature flag off → get_agent_qa_service() None
"""

from __future__ import annotations

import json

from app.agent.context import ToolServices
from app.agent.middleware import DuplicateToolCallMiddleware, sanitize_tool_error
from app.agent.runtime import build_agent, build_tools
from app.core.config import Settings
from app.services.agent_qa import AgentQaService, get_agent_qa_service


def test_six_tools_registered():
    names = [t.name for t in build_tools()]
    assert names == [
        "get_financial_facts",
        "lookup_financial_term",
        "search_news",
        "search_disclosures",
        "get_disclosure_values",
        "search_research_reports",
    ]


def test_build_agent_assembles_without_api_call():
    cfg = Settings()
    agent = build_agent(cfg, api_key="dummy", base_url="https://api.upstage.ai/v1")
    assert agent is not None  # create_agent 로 조립됨(우리가 StateGraph 를 직접 만들지 않음)


def test_sanitize_tool_error_hides_internal():
    msg = sanitize_tool_error(RuntimeError("db dsn secret"))
    assert "secret" not in msg and "dsn" not in msg


class _Req:
    def __init__(self, name, args, call_id="t1"):
        self.tool_call = {"name": name, "args": args, "id": call_id}
        self.tool_name = name


def test_duplicate_tool_call_blocked_on_repeat():
    mw = DuplicateToolCallMiddleware(max_repeats=1)
    calls = {"n": 0}

    def handler(req):
        calls["n"] += 1
        return "real-result"

    req = _Req("search_news", {"stock_code": "005930", "query": "호재"})
    # 1회차: 통과
    assert mw.wrap_tool_call(req, handler) == "real-result"
    # 2회차(동일 인자): 차단 → ToolMessage 반환, handler 미호출
    blocked = mw.wrap_tool_call(req, handler)
    assert calls["n"] == 1
    payload = json.loads(blocked.content)
    assert payload["status"] == "error"


def test_duplicate_middleware_allows_different_args():
    mw = DuplicateToolCallMiddleware(max_repeats=1)
    hits = []

    def handler(req):
        hits.append(req.tool_call["args"])
        return "ok"

    mw.wrap_tool_call(_Req("search_news", {"q": "a"}), handler)
    mw.wrap_tool_call(_Req("search_news", {"q": "b"}), handler)  # 다른 인자 → 허용
    assert len(hits) == 2


class _FakeAgent:
    def __init__(self, out=None, raise_exc=None, hang=False):
        self._out = out or {"messages": []}
        self._raise = raise_exc
        self._hang = hang

    def invoke(self, payload, context=None, config=None):
        if self._raise:
            raise self._raise
        if self._hang:
            import time

            time.sleep(5)
        return self._out


def _svc_with(agent, timeout=8.0):
    cfg = Settings(agent_timeout_seconds=timeout)
    svc = AgentQaService.__new__(AgentQaService)
    svc._cfg = cfg
    svc._services = ToolServices(facts=None, retriever=None, reports=None)
    svc._agent = agent
    return svc


class _Msg:
    def __init__(self, type_, content="", tool_calls=None):
        self.type = type_
        self.content = content
        self.tool_calls = tool_calls or []


def test_agent_qa_extracts_answer_and_toolcalls():
    out = {
        "messages": [
            _Msg("ai", "", [{"name": "get_financial_facts"}]),
            _Msg("tool", "..."),
            _Msg("ai", "삼성전자 2025년 영업이익은 6조원입니다. [1]"),
        ]
    }
    svc = _svc_with(_FakeAgent(out=out))
    r = svc.answer("영업이익 얼마?", stock_code="005930")
    assert r.stop_reason == "completed"
    assert "6조원" in r.answer
    assert [c.name for c in r.tool_calls] == ["get_financial_facts"]
    assert r.model_calls == 2


def test_agent_qa_timeout_returns_safe_error():
    svc = _svc_with(_FakeAgent(hang=True), timeout=0.5)
    r = svc.answer("느린 질문", stock_code="005930")
    assert r.stop_reason == "timeout" and r.answer == "" and r.error


def test_agent_qa_exception_returns_safe_error():
    svc = _svc_with(_FakeAgent(raise_exc=RuntimeError("internal secret")))
    r = svc.answer("오류 질문", stock_code="005930")
    assert r.stop_reason == "error"
    assert "secret" not in (r.error or "")


def test_feature_flag_off_returns_none():
    get_agent_qa_service.cache_clear()
    assert get_agent_qa_service() is None  # 기본 agent_enabled=False
