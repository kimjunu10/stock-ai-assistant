"""Phase 5.5-E 검증기·trace 단위 테스트 (LLM·DB 없음).

- collect_evidence: Tool payload 에서 source_id·숫자·value_kind 수집
- validate_answer: 존재하지 않는 인용, 근거 없는 재무 숫자 검출(숫자 미수정)
- AgentTrace: 안전 로그 dict(비밀·본문 미포함)
- AgentQaService._extract + answer: Tool payload 파싱 → 검증·trace 조립
"""

from __future__ import annotations

from app.agent.trace import AgentTrace, ToolTrace
from app.agent.validator import collect_evidence, validate_answer


def _fin_payload():
    return {
        "status": "ok",
        "data": {"facts": [{"value_won": 6000000000000, "value_kind": "actual_value"}]},
        "sources": [
            {
                "source_id": "005930/2025/11011",
                "source_type": "financial",
                "value_kind": "actual_value",
            }
        ],
    }


def test_collect_evidence_gathers_sources_and_numbers():
    ev = collect_evidence([_fin_payload()])
    assert "005930/2025/11011" in ev.source_ids
    assert "6000000000000" in ev.numeric_cores
    assert ev.has_financial is True
    assert "actual_value" in ev.value_kinds


def test_validate_flags_nonexistent_citation():
    ev = collect_evidence([])  # 근거 출처 0
    r = validate_answer("결론입니다 [1].", ev)
    assert not r.ok
    assert any("인용" in e for e in r.errors)


def test_validate_flags_unsupported_number():
    ev = collect_evidence([{"status": "no_data", "data": {}, "sources": []}])
    r = validate_answer("영업이익은 6,000,000,000,000원입니다.", ev)
    assert not r.ok
    assert any("숫자" in e for e in r.errors)


def test_validate_passes_when_number_supported():
    ev = collect_evidence([_fin_payload()])
    # 인용 없고, 재무 근거 있음 → 통과
    r = validate_answer("영업이익은 6조원 수준입니다.", ev)
    assert r.ok


def test_validate_does_not_mutate_numbers():
    ev = collect_evidence([])
    answer = "매출 333,605,938,000,000원"
    r = validate_answer(answer, ev)
    # 검증기는 답변 문자열을 바꾸지 않는다(오류만 기록)
    assert answer == "매출 333,605,938,000,000원"
    assert not r.ok


def test_trace_log_dict_has_no_secrets():
    t = AgentTrace(
        request_id="req1",
        model_calls=2,
        tool_calls=[ToolTrace(name="get_financial_facts", status="ok", result_count=1)],
        source_ids=["005930/2025/11011"],
        stop_reason="completed",
        validation_errors=[],
        total_latency_ms=1234,
    )
    d = t.to_log_dict()
    flat = str(d)
    # 식별자·지표만. 비밀·원문 본문 키워드가 없어야 한다.
    assert "api_key" not in flat and "password" not in flat and "raw_text" not in flat
    assert d["tool_calls"][0]["name"] == "get_financial_facts"
    assert d["total_latency_ms"] == 1234


def test_extract_parses_tool_payload():
    from langchain_core.messages import AIMessage, ToolMessage

    from app.services.agent_qa import AgentQaService

    out = {
        "messages": [
            AIMessage(
                content="", tool_calls=[{"name": "get_financial_facts", "args": {}, "id": "t1"}]
            ),
            ToolMessage(
                content='{"status":"ok","data":{"facts":[{"value_won":6000000000000}]},'
                '"sources":[{"source_id":"S1","source_type":"financial"}]}',
                tool_call_id="t1",
                name="get_financial_facts",
            ),
            AIMessage(content="영업이익은 6조원입니다."),
        ]
    }
    answer, tool_calls, model_calls, payloads, in_tok, out_tok = AgentQaService._extract(out)
    assert answer == "영업이익은 6조원입니다."
    assert tool_calls[0].name == "get_financial_facts"
    assert tool_calls[0].status == "ok" and tool_calls[0].result_count == 1
    assert payloads and payloads[0]["sources"][0]["source_id"] == "S1"
    assert model_calls == 2
