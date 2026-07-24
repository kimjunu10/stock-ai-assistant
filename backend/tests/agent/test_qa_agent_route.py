"""Phase 5.5-D API 연결 테스트. 외부 호출은 monkeypatch 로 무해화(실제 LLM·DB 없음).

- flag off(기본): 기존 결정론적 경로 유지 + query_plan(deprecated) 노출, execution=None
- flag on: Agent 경로 → execution 채워짐, tool_calls 반영
- 스트림: Agent 경로 SSE 이벤트(agent_start/tool_start/tool_end/delta/done)
- 기존 요청 계약(question/stock_code/context_source_id) 유지
"""

from __future__ import annotations

import app.api.routes.qa as qa_route
from app.schemas.qa import Source


class _FakeFactsResult:
    answer = "결정론적 답변 [1]"
    sources = [Source(citation=1, title="뉴스").model_dump()]
    numeric_sources = []
    report_sources = []
    term = None
    invalid_citations = []
    latency_ms = {"generate": 10}
    plan = {"need_financials": True, "need_documents": False}


class _FakeFactsService:
    def answer(self, q, **k):
        return _FakeFactsResult()


class _FakeAgentResult:
    def __init__(self):
        from app.services.agent_qa import AgentToolCall

        self.answer = "에이전트 답변"
        self.tool_calls = [AgentToolCall(name="get_financial_facts", status="ok")]
        self.model_calls = 2
        self.stop_reason = "completed"
        self.error = None


class _FakeAgentService:
    def answer(self, q, **k):
        return _FakeAgentResult()


def _client(monkeypatch, *, agent):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    monkeypatch.setattr(qa_route, "get_qa_service", lambda: _FakeFactsService())
    monkeypatch.setattr(
        qa_route, "get_agent_qa_service", lambda: _FakeAgentService() if agent else None
    )
    app = FastAPI()
    app.include_router(qa_route.router)
    return TestClient(app)


def test_flag_off_uses_deterministic_path(monkeypatch):
    client = _client(monkeypatch, agent=False)
    resp = client.post("/qa", json={"question": "영업이익 얼마?", "stock_code": "005930"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["answer"] == "결정론적 답변 [1]"
    assert body["execution"] is None  # Agent 경로 아님
    assert body["query_plan"] == {"need_financials": True, "need_documents": False}
    assert body["sources"][0]["citation"] == 1  # 기존 계약 유지


def test_flag_on_uses_agent_path(monkeypatch):
    client = _client(monkeypatch, agent=True)
    resp = client.post("/qa", json={"question": "영업이익 얼마?", "stock_code": "005930"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["answer"] == "에이전트 답변"
    assert body["execution"]["agent"] is True
    assert body["execution"]["tool_calls"][0]["name"] == "get_financial_facts"
    assert body["execution"]["model_calls"] == 2
    assert body["sources"] == []  # Agent 경로는 sources 별도 처리


def test_agent_stream_emits_sse_events(monkeypatch):
    client = _client(monkeypatch, agent=True)
    with client.stream(
        "POST", "/qa/stream", json={"question": "영업이익 얼마?", "stock_code": "005930"}
    ) as resp:
        text = "".join(chunk for chunk in resp.iter_text())
    assert "event: agent_start" in text
    assert "event: tool_start" in text
    assert "event: tool_end" in text
    assert "event: delta" in text
    assert "event: done" in text


def test_deterministic_stream_unchanged(monkeypatch):
    """flag off 스트림은 기존 sources→token→done 형식 유지."""

    class _FakeStreamService:
        def stream(self, q, **k):
            return ([], [], [], None, iter(["토큰1", "토큰2"]))

    monkeypatch.setattr(qa_route, "get_qa_service", lambda: _FakeStreamService())
    monkeypatch.setattr(qa_route, "get_agent_qa_service", lambda: None)
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()
    app.include_router(qa_route.router)
    client = TestClient(app)
    with client.stream(
        "POST", "/qa/stream", json={"question": "뉴스", "stock_code": "005930"}
    ) as r:
        text = "".join(c for c in r.iter_text())
    assert "event: sources" in text and "event: token" in text and "event: done" in text
    assert "event: agent_start" not in text
