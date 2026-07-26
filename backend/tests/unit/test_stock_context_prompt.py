"""UI 문맥 종목이 프롬프트에 실리는지 검증.

운영 결함: 화면에서 삼성전자가 선택돼 있고 요청에 stock_code=005930 이 실려 있는데도
"어제 주가 어케됨?" 에 Agent 가 종목을 되물었다. 원인은 프롬프트에 문맥 종목이
주입되지 않아 모델이 어떤 종목인지 알 수 없었던 것.

질문 문자열을 파싱하거나 회사명을 코드로 매핑하지 않는다 — 서버가 확정한 코드만 싣는다.
"""

from __future__ import annotations

from app.agent.prompts import financial_agent_system_prompt

_BASE = {
    "current_datetime": "2026-07-26T16:31:00+09:00",
    "current_date": "2026-07-26",
    "timezone": "Asia/Seoul",
}


def test_stock_context_is_injected_when_present():
    prompt = financial_agent_system_prompt(**_BASE, stock_code="005930")
    assert "현재 종목 문맥(서버 확정)" in prompt
    assert "005930" in prompt
    assert "종목을 되묻지 않는다" in prompt


def test_no_stock_context_block_without_stock_code():
    """종목 문맥이 없으면 블록 자체가 붙지 않는다(없는 종목을 가정하지 않음)."""
    prompt = financial_agent_system_prompt(**_BASE, stock_code=None)
    assert "현재 종목 문맥" not in prompt


def test_stock_context_allows_user_specified_other_stock():
    """문맥 종목이 있어도 사용자가 다른 종목을 말하면 그 종목을 쓰라고 지시한다."""
    prompt = financial_agent_system_prompt(**_BASE, stock_code="005930")
    assert "사용자가 다른 종목을 명시한 경우에만 그 종목을 쓴다" in prompt


def test_stock_and_event_context_coexist():
    """종목 문맥과 사건 문맥이 함께 실려도 서로 지우지 않는다."""
    prompt = financial_agent_system_prompt(
        **_BASE,
        stock_code="005930",
        event_status="resolved",
        event_title="엔비디아 본사 회동",
        event_date="2026-07-25",
    )
    assert "현재 종목 문맥(서버 확정)" in prompt
    assert "현재 사건 문맥(서버 확정)" in prompt
    assert "2026-07-25" in prompt
