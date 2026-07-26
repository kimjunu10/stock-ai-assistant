"""최소 요청 계약 테스트 (prompt.md §8).

후속 질문 정확성에 필요한 요청 생성 계약만 검사한다(프런트 디자인·차트·브라우저 제외).
- 직전 응답의 사건 식별자가 다음 요청에 포함됨
- 사용자가 선택한 사건 식별자가 다음 요청에 포함됨
- 공시·리포트의 현재 문맥 식별자가 다음 요청에 포함됨
- 서로 다른 사건이 여러 개면 임의 사건을 요청에 넣지 않음
- 중단·초기화된 대화의 이전 사건 문맥이 남지 않음

검사 위치: 공통 요청 스키마(QaRequest)와 이를 런타임 문맥으로 옮기는 경계
(AgentQaService._context). 실제 구조상 이 두 곳이 모든 클라이언트가 통과하는
단일 요청 생성 계층이다.
"""

from __future__ import annotations

import app.api.routes.qa as qa_route
from app.agent.event_reference import resolve_event
from app.schemas.qa import EventContext, QaRequest
from app.services.agent_qa import AgentQaService


class _Result:
    answer = "답변"
    tool_calls: list = []
    model_calls = 1
    stop_reason = "completed"
    error = None
    validation_errors: list = []
    source_ids: list = []
    report_opinions: list = []
    sources: list = []
    visualizations: list = []
    warnings: list = []


class _Recorder:
    """라우트가 서비스에 넘긴 인자를 기록한다(요청 → 실행 계약 경계)."""

    calls: list = []

    def answer(self, q, **k):
        type(self).calls.append(k)
        return _Result()


def _client(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    _Recorder.calls = []
    monkeypatch.setattr(qa_route, "get_agent_qa_service", lambda: _Recorder())
    app = FastAPI()
    app.include_router(qa_route.router)
    return TestClient(app)


_EVENT = {
    "event_id": "news:evt-1",
    "stock_code": "005930",
    "published_at": "2026-07-22T09:00:00+09:00",
    "title": "HBM 공급계약 체결",
}


# ── 직전 응답의 사건 식별자가 다음 요청에 포함 ────────────────────
def test_event_context_reaches_service(monkeypatch):
    client = _client(monkeypatch)
    r = client.post(
        "/qa",
        json={
            "question": "그 뉴스 이후 주가 어때?",
            "stock_code": "005930",
            "event_context": [_EVENT],
        },
    )
    assert r.status_code == 200
    kwargs = _Recorder.calls[-1]
    assert [e.event_id for e in kwargs["event_context"]] == ["news:evt-1"]
    assert kwargs["event_context"][0].published_at == "2026-07-22T09:00:00+09:00"


def test_selected_event_id_reaches_service(monkeypatch):
    client = _client(monkeypatch)
    client.post(
        "/qa",
        json={
            "question": "이 뉴스 이후 주가는?",
            "event_context": [_EVENT, {**_EVENT, "event_id": "news:evt-2", "title": "다른 사건"}],
            "selected_event_id": "news:evt-2",
        },
    )
    assert _Recorder.calls[-1]["selected_event_id"] == "news:evt-2"


def test_stream_route_sends_same_event_contract(monkeypatch):
    """/qa 와 /qa/stream 이 동일한 사건 문맥을 전달한다(의미 불일치 0건)."""
    client = _client(monkeypatch)
    body = {
        "question": "그 뉴스 이후 주가 어때?",
        "event_context": [_EVENT],
        "selected_event_id": "news:evt-1",
    }
    client.post("/qa", json=body)
    with client.stream("POST", "/qa/stream", json=body) as resp:
        assert resp.status_code == 200
        resp.read()
    assert len(_Recorder.calls) == 2
    a, b = _Recorder.calls
    assert [e.event_id for e in a["event_context"]] == [e.event_id for e in b["event_context"]]
    assert a["selected_event_id"] == b["selected_event_id"]


# ── 공시·리포트의 현재 문맥 식별자 ────────────────────────────────
def test_disclosure_context_identifier_reaches_service(monkeypatch):
    client = _client(monkeypatch)
    client.post(
        "/qa",
        json={
            "question": "이 공시 쉽게 정리해줘",
            "context_source_id": "dart:20260722000123",
            "context_source_type": "dart_document",
            "document_id": "20260722000123",
        },
    )
    kwargs = _Recorder.calls[-1]
    assert kwargs["source_id"] == "dart:20260722000123"
    assert kwargs["source_type"] == "dart_document"
    assert kwargs["document_id"] == "20260722000123"


def test_report_page_context_reaches_service(monkeypatch):
    client = _client(monkeypatch)
    client.post(
        "/qa",
        json={"question": "이 리포트 요약", "context_source_id": "report:x", "report_page": 3},
    )
    assert _Recorder.calls[-1]["report_page"] == 3


# ── 중단·초기화된 대화에 이전 사건 문맥이 남지 않음 ───────────────
def test_reset_conversation_carries_no_event_context(monkeypatch):
    """사건 문맥은 요청 단위로만 전달된다. 서버가 대화별로 보관하지 않는다."""
    client = _client(monkeypatch)
    client.post("/qa", json={"question": "그 뉴스 이후?", "event_context": [_EVENT]})
    # 초기화 후 새 요청(사건 문맥 없음)
    client.post("/qa", json={"question": "삼성전자 현재 주가는?", "stock_code": "005930"})
    assert _Recorder.calls[-1]["event_context"] == []
    assert _Recorder.calls[-1]["selected_event_id"] is None


def test_request_defaults_have_no_event_context():
    req = QaRequest(question="삼성전자 현재 주가는?")
    assert req.event_context == []
    assert req.selected_event_id is None


# ── 여러 사건이면 임의 사건을 쓰지 않음(실행 계약 경계) ───────────
def _ctx(events, *, selected=None):
    """요청 사건 문맥 → 런타임 문맥 변환(Agent 생성 없이 경계만 검사)."""
    svc = object.__new__(AgentQaService)
    svc._services = object()
    return svc._context(
        "005930", None, None, None, None, None, resolve_event(events, selected_event_id=selected)
    )


def test_ambiguous_context_does_not_pick_any_event():
    ctx = _ctx(
        [
            EventContext(event_id="news:a", title="A", published_at="2026-07-22"),
            EventContext(event_id="news:b", title="B", published_at="2026-07-18"),
        ]
    )
    assert ctx.event_status == "ambiguous"
    assert ctx.event_id is None
    assert ctx.event_date is None
    assert {c.event_id for c in ctx.event_candidates} == {"news:a", "news:b"}


def test_resolved_context_carries_event_date():
    ctx = _ctx(
        [EventContext(event_id="news:a", title="A", published_at="2026-07-22T09:00:00+09:00")]
    )
    assert ctx.event_status == "resolved"
    assert ctx.event_id == "news:a"
    assert ctx.event_date == "2026-07-22"


def test_event_without_published_at_is_not_resolved():
    """발표일이 없으면 resolved 로 승격하지 않는다(날짜 추정 금지)."""
    ctx = _ctx([EventContext(event_id="news:a", title="A")])
    assert ctx.event_status != "resolved"
    assert ctx.event_date is None


def test_empty_context_is_none_status():
    ctx = _ctx([])
    assert ctx.event_status == "none"
    assert ctx.event_id is None
