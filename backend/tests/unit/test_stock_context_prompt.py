"""UI 문맥 종목이 프롬프트에 실리는지 검증.

운영 결함: 화면에서 삼성전자가 선택돼 있고 요청에 stock_code=005930 이 실려 있는데도
"어제 주가 어케됨?" 에 Agent 가 종목을 되물었다. 원인은 프롬프트에 문맥 종목이
주입되지 않아 모델이 어떤 종목인지 알 수 없었던 것.

질문 문자열을 파싱하거나 회사명을 코드로 매핑하지 않는다 — 서버가 확정한 코드와
공식 회사명만 싣는다.
"""

from __future__ import annotations

from app.agent.prompts import financial_agent_system_prompt

_BASE = {
    "current_datetime": "2026-07-26T16:31:00+09:00",
    "current_date": "2026-07-26",
    "timezone": "Asia/Seoul",
}


def test_stock_context_is_injected_when_present():
    prompt = financial_agent_system_prompt(**_BASE, stock_code="005380", company_name="현대자동차")
    assert "현재 종목 문맥(서버 확정)" in prompt
    assert "005380 / 현대자동차" in prompt
    assert "종목을 되묻지 않는다" in prompt


def test_stock_context_does_not_guess_company_name_when_missing():
    prompt = financial_agent_system_prompt(**_BASE, stock_code="005380", company_name=None)
    assert "공식 회사명: 확인 불가" in prompt
    assert "종목코드만 보고 회사명을 추측하거나 만들어내지 않는다" in prompt
    assert "현대" not in prompt


def test_no_stock_context_block_without_stock_code():
    """종목 문맥이 없으면 블록 자체가 붙지 않는다(없는 종목을 가정하지 않음)."""
    prompt = financial_agent_system_prompt(**_BASE, stock_code=None)
    assert "현재 종목 문맥" not in prompt


def test_stock_context_refuses_to_substitute_selected_stock_for_other_company():
    """다른 회사 질문에 선택 종목 자료로 대신 답하지 않도록 지시한다."""
    prompt = financial_agent_system_prompt(**_BASE, stock_code="005930", company_name="삼성전자")
    assert "사용자가 다른 회사를 명시하면 이 종목의 자료로 대신 답하지 않는다" in prompt
    assert "종목 선택을 변경해 달라고 안내" in prompt


def test_stock_and_event_context_coexist():
    """종목 문맥과 사건 문맥이 함께 실려도 서로 지우지 않는다."""
    prompt = financial_agent_system_prompt(
        **_BASE,
        stock_code="005930",
        company_name="삼성전자",
        event_status="resolved",
        event_title="엔비디아 본사 회동",
        event_date="2026-07-25",
    )
    assert "현재 종목 문맥(서버 확정)" in prompt
    assert "현재 사건 문맥(서버 확정)" in prompt
    assert "2026-07-25" in prompt


def test_document_context_injected_for_research_report():
    """화면에 열린 리포트 문맥(report_id)이 프롬프트에 실린다(round3 D케이스).

    운영 결함: "이 리포트 목표주가 근거 알려줘" 처럼 지시 표현으로 물어도
    문맥에 report_id 가 있다는 사실 자체가 모델에게 전혀 노출되지 않아
    Agent 가 항상 어떤 리포트인지 되물었다.
    """
    prompt = financial_agent_system_prompt(
        **_BASE, source_type="research_report", source_id="rep-123"
    )
    assert "현재 문서 문맥(서버 확정)" in prompt
    assert "rep-123" in prompt
    assert "되묻지 않는다" in prompt


def test_no_document_context_without_source_id():
    prompt = financial_agent_system_prompt(**_BASE, source_type="research_report", source_id=None)
    assert "현재 문서 문맥" not in prompt


def test_news_context_is_injected_as_primary_event():
    """뉴스 상세에서 연 챗봇은 선택한 사건을 서버 확정 문맥으로 사용한다."""
    prompt = financial_agent_system_prompt(**_BASE, source_type="news_event", source_id="cluster-1")
    assert "현재 뉴스 문맥(서버 확정)" in prompt
    assert "cluster-1" in prompt
    assert "최우선 근거" in prompt
    assert "같은 종목의 다른 사건" in prompt


def test_primary_news_content_is_pinned_for_short_follow_up_questions():
    prompt = financial_agent_system_prompt(
        **_BASE,
        source_type="news_event",
        source_id="77",
        primary_source={
            "context_source_id": "77",
            "source_type": "news_event",
            "title": "한화오션 LNG선 수주",
            "published_at": "2026-07-27",
            "sentiment": "positive",
            "content": "한화오션이 고부가가치 LNG 운반선 4척을 수주했다.",
        },
    )

    assert "모든 대화 턴에 고정" in prompt
    assert "한화오션 LNG선 수주" in prompt
    assert "LNG 운반선 4척" in prompt
    assert "'호재야/악재야'" in prompt
    assert "최근 호재·악재 목록 요청이 아니라" in prompt
    assert "어떤 자료인지 되묻지 않는다" in prompt
    assert "요약해 되풀이하지 말고" in prompt


def test_beginner_document_explanation_is_semantic_not_article_restatement():
    prompt = financial_agent_system_prompt(**_BASE)
    assert "첫 문장은 반드시 `쉽게 말해, ...`" in prompt
    assert "용어 = 쉬운 뜻" in prompt
    assert "원문 문장을 줄이거나 순서만 바꾼 요약을 하지 않는다" in prompt
    assert "없는 배수·수익·주가 방향은 만들지 않는다" in prompt


def test_answer_style_is_not_a_rigid_template():
    prompt = financial_agent_system_prompt(**_BASE)
    assert "고정된 출력 틀을 사용하지 않는다" in prompt
    assert "반드시 아래 3단 구조" not in prompt
    assert "`투자자가 볼 점` 같은 고정 맺음말" in prompt


def test_compound_event_question_uses_search_event_ref_then_return_tool():
    prompt = financial_agent_system_prompt(**_BASE)
    assert "검색 결과의 event_ref(source_type/source_id)" in prompt
    assert "calculate_event_return을 호출한다" in prompt
    assert "날짜는 넘기거나 추정하지 않는다" in prompt


def test_disclosure_context_is_injected():
    prompt = financial_agent_system_prompt(
        **_BASE, source_type="dart_document", source_id="20260727000123"
    )
    assert "현재 공시 문맥(서버 확정)" in prompt
    assert "20260727000123" in prompt
    assert "되묻지 않는다" in prompt


def test_unknown_source_type_does_not_create_document_context():
    prompt = financial_agent_system_prompt(**_BASE, source_type="unknown", source_id="x")
    assert "현재 뉴스 문맥" not in prompt
    assert "현재 공시 문맥" not in prompt
    assert "현재 문서 문맥" not in prompt
