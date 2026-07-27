"""Phase 5.5-C Agent 구현 단위 테스트 (LLM 실호출 없음).

- Tool 8개 등록·이름 확인(Phase 6 주가 Tool 포함)
- create_agent 조립 성공(더미 키, invoke 안 함)
- DuplicateToolCallMiddleware: 동일 Tool+인자 반복 차단, 다른 인자는 허용
- sanitize_tool_error: 내부 예외 비노출
- AgentQaService: timeout/에러 시 안전 응답, 내부추론 미저장(fake agent)
- feature flag off → get_agent_qa_service() None
"""

from __future__ import annotations

import json
from datetime import datetime
from zoneinfo import ZoneInfo

from app.agent.context import ToolServices
from app.agent.middleware import DuplicateToolCallMiddleware, sanitize_tool_error
from app.agent.prompts import financial_agent_system_prompt
from app.agent.runtime import build_agent, build_tools
from app.core.config import Settings
from app.services.agent_qa import AgentQaService, get_agent_qa_service


def test_eight_tools_registered():
    # Phase 6 에서 주가 Tool 2개를 추가(6→8).
    names = [t.name for t in build_tools()]
    assert names == [
        "get_financial_facts",
        "lookup_financial_term",
        "search_news",
        "search_disclosures",
        "get_disclosure_values",
        "search_research_reports",
        "get_stock_prices",
        "calculate_event_return",
    ]


class _FakeRuntime:
    def __init__(self, ctx_stock=None):
        self.context = type(
            "C",
            (),
            {"stock_code": ctx_stock, "stock_context_events": []},
        )()


def test_resolve_stock_code_rejects_code_different_from_context():
    from app.agent.runtime import _resolve_stock_code

    runtime = _FakeRuntime(ctx_stock="000660")
    assert _resolve_stock_code("005930", runtime, tool_name="get_financial_facts") == ""
    assert runtime.context.stock_context_events == [
        {
            "code": "STOCK_CONTEXT_MISMATCH",
            "tool_name": "get_financial_facts",
            "provided_stock_code": "005930",
            "selected_stock_code": "000660",
        }
    ]


def test_resolve_stock_code_only_accepts_selected_company_alias_or_empty():
    from app.agent.runtime import _resolve_stock_code

    assert _resolve_stock_code("삼성전자", _FakeRuntime(ctx_stock="005930")) == "005930"
    assert _resolve_stock_code("", _FakeRuntime(ctx_stock="005930")) == "005930"


def test_resolve_stock_code_never_falls_back_unsupported_company_to_context():
    from app.agent.runtime import _resolve_stock_code

    runtime = _FakeRuntime(ctx_stock="005930")
    assert _resolve_stock_code("AAPL", runtime, tool_name="get_financial_facts") == "AAPL"
    assert runtime.context.stock_context_events[0]["code"] == "UNSUPPORTED_STOCK"


def test_resolve_stock_code_no_context_keeps_original_for_safe_error():
    """문맥 종목코드도 없으면 원값 유지 → 입력 스키마 검증이 안전 오류로 처리."""
    from app.agent.runtime import _resolve_stock_code

    assert _resolve_stock_code("삼성", _FakeRuntime(ctx_stock=None)) == "삼성"
    # 질문 문자열을 파싱하거나 회사명을 코드로 매핑하지 않는다(하드코딩 없음).
    assert _resolve_stock_code("삼성", _FakeRuntime(ctx_stock="삼성전자")) == "삼성"


def test_build_agent_assembles_without_api_call():
    cfg = Settings()
    agent = build_agent(cfg, api_key="dummy", base_url="https://api.upstage.ai/v1")
    assert agent is not None  # create_agent 로 조립됨(우리가 StateGraph 를 직접 만들지 않음)


def test_runtime_prompt_uses_server_date_not_model_knowledge():
    prompt = financial_agent_system_prompt(
        current_datetime="2026-07-25T22:53:02+09:00",
        current_date="2026-07-25",
        timezone="Asia/Seoul",
    )
    assert "2026-07-25" in prompt
    assert "Asia/Seoul" in prompt
    assert "학습 기준일" in prompt


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
        self.invoke_count = 0
        self.last_context = None

    def invoke(self, payload, context=None, config=None):
        self.invoke_count += 1
        self.last_context = context
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
    def __init__(self, type_, content="", tool_calls=None, name=None):
        self.type = type_
        self.content = content
        self.tool_calls = tool_calls or []
        self.name = name


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


def test_agent_qa_allows_selected_context_with_or_without_same_company_name():
    for question in ("올해 실적 알려줘", "삼성전자 올해 실적 알려줘"):
        agent = _FakeAgent(out={"messages": [_Msg("ai", "정상 답변")]})
        r = _svc_with(agent).answer(question, stock_code="005930")

        assert r.stop_reason == "completed"
        assert agent.invoke_count == 1
        assert agent.last_context.stock_code == "005930"


def test_agent_qa_blocks_different_supported_company_before_agent_and_tools():
    agent = _FakeAgent()
    r = _svc_with(agent).answer("현대차 올해 실적 알려줘", stock_code="005930")

    assert r.error_code == "STOCK_CONTEXT_MISMATCH"
    assert r.stop_reason == "blocked"
    assert agent.invoke_count == 0
    assert r.model_calls == 0
    assert r.tool_calls == []
    assert r.sources == []


def test_agent_qa_blocks_unsupported_company_without_selected_stock_fallback():
    agent = _FakeAgent()
    r = _svc_with(agent).answer("애플 올해 실적 알려줘", stock_code="005930")

    assert r.error_code == "UNSUPPORTED_STOCK"
    assert agent.invoke_count == 0
    assert r.tool_calls == []
    assert r.sources == []
    assert "삼성전자 005930" not in r.answer
    assert "영업이익" not in r.answer


def test_agent_qa_blocks_multi_stock_request_before_agent():
    agent = _FakeAgent()
    r = _svc_with(agent).answer("삼성전자와 애플 실적 비교", stock_code="005930")

    assert r.error_code == "MULTI_STOCK_NOT_SUPPORTED"
    assert agent.invoke_count == 0
    assert r.tool_calls == []


def test_agent_qa_blocks_stale_other_stock_event_context_before_agent():
    agent = _FakeAgent()
    event = type("Event", (), {"stock_code": "000660"})()

    r = _svc_with(agent).answer(
        "이 뉴스 이후 주가 알려줘",
        stock_code="005930",
        event_context=[event],
    )

    assert r.error_code == "STOCK_CONTEXT_MISMATCH"
    assert agent.invoke_count == 0
    assert r.tool_calls == []


def test_agent_qa_blocks_final_answer_when_source_stock_differs(caplog):
    payload = {
        "status": "ok",
        "data": {"facts": []},
        "sources": [
            {
                "source_id": "000660/2025/영업이익",
                "source_type": "financial",
                "stock_code": "000660",
            }
        ],
    }
    out = {
        "messages": [
            _Msg(
                "ai",
                "",
                [
                    {
                        "name": "get_financial_facts",
                        "args": {"stock_code": "005930"},
                    }
                ],
            ),
            _Msg("tool", json.dumps(payload), name="get_financial_facts"),
            _Msg("ai", "오염된 최종 답변"),
        ]
    }

    r = _svc_with(_FakeAgent(out=out)).answer("올해 실적 알려줘", stock_code="005930")

    assert r.error_code == "STOCK_CONTEXT_MISMATCH"
    assert r.stop_reason == "blocked"
    assert r.answer != "오염된 최종 답변"
    assert r.sources == []
    assert r.visualizations == []
    assert "STOCK_CONTEXT_CONTAMINATION" in caplog.text
    assert "failed_layer=tool_source_validation" in caplog.text


def test_agent_context_captures_timezone_aware_kst_request_time():
    svc = _svc_with(_FakeAgent())
    ctx = svc._context(
        "005930",
        None,
        None,
        None,
        None,
        None,
        request_id="req-time",
        user_question="최근 뉴스 알려줘",
    )
    parsed = datetime.fromisoformat(ctx.current_datetime)
    assert ctx.current_date == parsed.date().isoformat()
    assert parsed.tzinfo is not None
    assert parsed.utcoffset() == ZoneInfo("Asia/Seoul").utcoffset(parsed)
    assert ctx.request_id == "req-time"
    assert ctx.user_question == "최근 뉴스 알려줘"


class _FakeStockNameFacts:
    def __init__(self, names):
        self.names = names

    def get_stock_name(self, stock_code):
        return self.names.get(stock_code)


def test_agent_context_resolves_company_name_by_stock_code():
    svc = _svc_with(_FakeAgent())
    svc._services.facts = _FakeStockNameFacts({"005380": "현대자동차"})

    ctx = svc._context("005380", None, None, None, None, None)

    assert ctx.stock_code == "005380"
    assert ctx.company_name == "현대자동차"


def test_agent_context_keeps_company_name_empty_when_lookup_has_no_match():
    svc = _svc_with(_FakeAgent())
    svc._services.facts = _FakeStockNameFacts({})

    ctx = svc._context("005380", None, None, None, None, None)

    assert ctx.stock_code == "005380"
    assert ctx.company_name is None


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


def test_all_stock_code_tools_use_context_fallback():
    """종목코드를 받는 Tool 은 전부 문맥 폴백을 거쳐야 한다.

    운영 결함 회귀: get_stock_prices·get_financial_facts·get_disclosure_values 가
    _resolve_stock_code 를 쓰지 않아, 화면에서 종목이 선택돼 있어도 모델이 코드를
    빠뜨리면 조회가 실패했다. 새 Tool 추가 시 폴백 누락을 여기서 잡는다.
    """
    import inspect

    from app.agent import runtime as rt

    src = inspect.getsource(rt.build_tools)
    all_tools = [t.name for t in build_tools()]
    # 종목코드를 인자로 받는 Tool (lookup_financial_term 은 용어만 받으므로 제외)
    stock_tools = [t for t in all_tools if t != "lookup_financial_term"]
    starts = {t: src.index(f"def {t}(") for t in all_tools}
    for name in stock_tools:
        # 각 Tool 함수 본문만 잘라 검사한다(다음 Tool 정의 직전까지).
        later = [s for s in starts.values() if s > starts[name]]
        body = src[starts[name] : min(later)] if later else src[starts[name] :]
        assert "_resolve_stock_code(" in body, f"{name} 이 문맥 종목 폴백을 쓰지 않음"
