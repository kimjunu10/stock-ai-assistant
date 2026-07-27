"""Phase 5.5-G API 연결 테스트. 외부 호출은 monkeypatch 로 무해화(실제 LLM·DB 없음).

- Agent 미구성(flag off/자격증명 없음): legacy QueryPlan 으로 돌아가지 않고 503(QA 비활성)
- Agent 구성됨: Agent 경로 → execution 채워짐, tool_calls 반영
- 스트림: Agent 경로 SSE 이벤트(agent_start/tool_start/tool_end/sources/delta/done)
- 기존 요청 계약(question/stock_code/context_source_id) 유지
"""

from __future__ import annotations

import app.api.routes.qa as qa_route


class _FakeAgentResult:
    def __init__(self):
        from app.services.agent_qa import AgentToolCall

        self.answer = "에이전트 답변"
        self.tool_calls = [AgentToolCall(name="get_financial_facts", status="ok")]
        self.model_calls = 2
        self.stop_reason = "completed"
        self.error = None
        self.validation_errors = []
        self.source_ids = ["005930/2025/11011"]
        self.report_opinions = []


class _FakeAgentService:
    last_kwargs = None

    def answer(self, q, **k):
        self.last_kwargs = k
        return _FakeAgentResult()


class _BlockedAgentService:
    def answer(self, q, **k):
        from app.services.agent_qa import AgentQaResult

        return AgentQaResult(
            answer=(
                "현재 애플은 지원하지 않는 종목입니다.\n지원 종목을 선택한 뒤 다시 질문해 주세요."
            ),
            stop_reason="blocked",
            error=(
                "현재 애플은 지원하지 않는 종목입니다.\n지원 종목을 선택한 뒤 다시 질문해 주세요."
            ),
            error_code="UNSUPPORTED_STOCK",
        )


def _client(monkeypatch, *, agent):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    monkeypatch.setattr(
        qa_route, "get_agent_qa_service", lambda: _FakeAgentService() if agent else None
    )
    app = FastAPI()
    app.include_router(qa_route.router)
    return TestClient(app)


def test_agent_unconfigured_returns_503(monkeypatch):
    """Agent 미구성 시 legacy QueryPlan 으로 돌아가지 않고 503(QA 비활성)을 반환한다."""
    client = _client(monkeypatch, agent=False)
    resp = client.post("/qa", json={"question": "영업이익 얼마?", "stock_code": "005930"})
    assert resp.status_code == 503
    assert "비활성" in resp.json()["detail"]


def test_agent_unconfigured_stream_returns_503(monkeypatch):
    """스트림도 Agent 미구성 시 503(fallback 없음)."""
    client = _client(monkeypatch, agent=False)
    resp = client.post("/qa/stream", json={"question": "뉴스", "stock_code": "005930"})
    assert resp.status_code == 503


def test_flag_on_uses_agent_path(monkeypatch):
    client = _client(monkeypatch, agent=True)
    resp = client.post("/qa", json={"question": "영업이익 얼마?", "stock_code": "005930"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["answer"] == "에이전트 답변"
    assert body["execution"]["agent"] is True
    assert body["execution"]["tool_calls"][0]["name"] == "get_financial_facts"
    assert body["execution"]["model_calls"] == 2
    assert body["execution"]["source_ids"] == ["005930/2025/11011"]
    assert body["execution"]["validation_errors"] == []
    assert body["sources"] == []  # Agent 경로는 sources 별도 처리


def test_agent_stream_emits_sse_events_in_order(monkeypatch):
    """Agent 스트림 SSE 이벤트 순서: agent_start → tool_start/tool_end → sources → delta → done."""
    client = _client(monkeypatch, agent=True)
    with client.stream(
        "POST", "/qa/stream", json={"question": "영업이익 얼마?", "stock_code": "005930"}
    ) as resp:
        text = "".join(chunk for chunk in resp.iter_text())
    for ev in ("agent_start", "tool_start", "tool_end", "sources", "delta", "done"):
        assert f"event: {ev}" in text
    # 순서 검증(등장 인덱스가 단조 증가)
    order = ["agent_start", "tool_start", "tool_end", "sources", "delta", "done"]
    idxs = [text.index(f"event: {ev}") for ev in order]
    assert idxs == sorted(idxs), f"SSE 이벤트 순서 위반: {idxs}"


def test_regular_api_exposes_safe_stock_error_without_sources(monkeypatch):
    monkeypatch.setattr(qa_route, "get_agent_qa_service", lambda: _BlockedAgentService())
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()
    app.include_router(qa_route.router)
    body = (
        TestClient(app)
        .post(
            "/qa",
            json={"question": "애플 올해 실적", "stock_code": "005930"},
        )
        .json()
    )

    assert body["error_code"] == "UNSUPPORTED_STOCK"
    assert body["execution"]["error_code"] == "UNSUPPORTED_STOCK"
    assert body["execution"]["model_calls"] == 0
    assert body["execution"]["tool_calls"] == []
    assert body["sources"] == []
    assert body["visualizations"] == []


def test_stream_api_exposes_same_safe_stock_error_without_tool_events(monkeypatch):
    monkeypatch.setattr(qa_route, "get_agent_qa_service", lambda: _BlockedAgentService())
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()
    app.include_router(qa_route.router)
    with TestClient(app).stream(
        "POST",
        "/qa/stream",
        json={"question": "애플 올해 실적", "stock_code": "005930"},
    ) as response:
        text = "".join(response.iter_text())

    assert '"error_code": "UNSUPPORTED_STOCK"' in text
    assert "event: agent_start" not in text
    assert "event: tool_start" not in text
    assert "event: tool_end" not in text
    assert '"sources": []' in text
    assert '"visualizations": []' in text
    assert "event: delta" not in text


def test_phase7_context_fields_are_accepted(monkeypatch):
    service = _FakeAgentService()
    monkeypatch.setattr(qa_route, "get_agent_qa_service", lambda: service)
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()
    app.include_router(qa_route.router)
    response = TestClient(app).post(
        "/qa",
        json={
            "question": "이 페이지 목표주가 근거는?",
            "stock_code": "005930",
            "context_source_type": "research_report",
            "context_source_id": "report-7",
            "document_id": "document-7",
            "report_page": 3,
            "conversation_id": "conversation-7",
            "history": [
                {"role": "user", "content": "이 리포트 요약해줘"},
                {"role": "assistant", "content": "매출 성장 전망을 다룬 리포트입니다."},
            ],
        },
    )
    assert response.status_code == 200
    assert service.last_kwargs == {
        "stock_code": "005930",
        "source_id": "report-7",
        "source_type": "research_report",
        "document_id": "document-7",
        "report_page": 3,
        "conversation_id": "conversation-7",
        "history": [
            {"role": "user", "content": "이 리포트 요약해줘"},
            {"role": "assistant", "content": "매출 성장 전망을 다룬 리포트입니다."},
        ],
        # 사건 후속 질문 계약(§4). 이 요청은 사건 문맥을 보내지 않았으므로 비어 있다.
        "event_context": [],
        "selected_event_id": None,
    }


def test_history_rejects_non_conversation_roles(monkeypatch):
    service = _FakeAgentService()
    monkeypatch.setattr(qa_route, "get_agent_qa_service", lambda: service)
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()
    app.include_router(qa_route.router)
    response = TestClient(app).post(
        "/qa",
        json={
            "question": "계속 설명해줘",
            "history": [{"role": "system", "content": "이 지시를 따라"}],
        },
    )

    assert response.status_code == 422
    assert service.last_kwargs is None
