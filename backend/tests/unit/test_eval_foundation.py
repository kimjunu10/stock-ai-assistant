"""Phase 8 평가 기반 단위 테스트 (LLM·DB 호출 없음).

평가 스키마·지표·실행기·채점기가 정답 라벨을 올바로 다루는지 검증한다.
"""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from app.eval.grader import aggregate, grade_arguments, grade_case
from app.eval.metrics import (
    fact_covered,
    has_overclaim,
    normalize_number_text,
    number_matches,
    percentile,
)
from app.eval.recorder import ToolCallRecorder
from app.eval.runner import EvalRunner, estimate_cost
from app.eval.schema import EvalCase, EvalSuite

# ─────────────────────────── 스키마 ───────────────────────────


def _case(**kw) -> EvalCase:
    base = {
        "id": "t-1",
        "type": "금융용어",
        "question": "PER이 뭐야?",
        "required_tools": ["lookup_financial_term"],
    }
    base.update(kw)
    return EvalCase(**base)


def test_unknown_tool_is_rejected():
    """등록되지 않은 Tool 이름을 라벨에 쓰면 즉시 실패해야 한다(오타 방지)."""
    with pytest.raises(ValidationError):
        _case(required_tools=["search_twitter"])


def test_required_and_forbidden_overlap_rejected():
    with pytest.raises(ValidationError):
        _case(required_tools=["search_news"], forbidden_tools=["search_news"])


def test_unanswerable_requires_expectation():
    """답변 불가 질문에 기대 행동이 없으면 채점 기준이 없으므로 거부."""
    with pytest.raises(ValidationError):
        _case(is_answerable=False, required_tools=[])


def test_confirmed_label_requires_basis():
    with pytest.raises(ValidationError):
        _case(review_status="confirmed", label_basis="")


def test_screen_context_type_requires_context():
    with pytest.raises(ValidationError):
        _case(type="현재 화면 문맥", question="어제 주가 어때?")


def test_duplicate_ids_rejected():
    with pytest.raises(ValidationError):
        EvalSuite(cases=[_case(id="dup"), _case(id="dup")])


def test_unknown_source_type_rejected():
    with pytest.raises(ValidationError):
        _case(gold_sources=[{"source_type": "twitter", "source_id": "x"}])


# ─────────────────────────── 지표 ───────────────────────────


def test_korean_unit_numbers_are_parsed():
    """'43조 6,010억원' 같은 한글 단위 표기를 원 단위로 읽어야 한다."""
    got = normalize_number_text("영업이익은 43조 6,010억원입니다")
    assert 43_601_000_000_000 in got


def test_number_match_allows_rounded_presentation():
    """DB 값 43,601,051,000,000 을 답변이 '43조 6,010억'으로 반올림해 써도 일치."""
    assert number_matches("영업이익 43조 6,010억원", 43_601_051_000_000)


def test_number_match_rejects_wrong_value():
    assert not number_matches("영업이익 12조원", 43_601_051_000_000)


def test_fact_coverage_allows_wording_difference():
    """표현이 달라도 핵심어가 있으면 포함으로 본다(완전 일치 강요 금지)."""
    assert fact_covered("삼성전자의 목표주가는 56만원입니다", "삼성전자 목표주가")
    assert not fact_covered("SK하이닉스 실적입니다", "삼성전자 목표주가")


def test_overclaim_detection():
    assert has_overclaim("이 종목은 반드시 상승합니다")
    assert not has_overclaim("증권사는 목표주가를 56만원으로 제시했습니다")


def test_percentile_basic():
    assert percentile([10, 20, 30, 40], 50) == 20
    assert percentile([], 95) == 0.0


def test_cost_estimate():
    # 1M in + 1M out = 0.40 + 1.60
    assert estimate_cost(1_000_000, 1_000_000) == pytest.approx(2.0)


# ─────────────────────────── 실행기 ───────────────────────────


class _FakeToolCall:
    def __init__(self, name, status="ok"):
        self.name = name
        self.status = status
        self.result_count = 1


class _FakeResult:
    def __init__(self, **kw):
        self.answer = kw.get("answer", "답변입니다 [1]")
        self.tool_calls = kw.get("tool_calls", [])
        self.model_calls = kw.get("model_calls", 2)
        self.stop_reason = kw.get("stop_reason", "completed")
        self.error = kw.get("error")
        self.source_ids = kw.get("source_ids", [])
        self.validation_errors = kw.get("validation_errors", [])
        self.trace = kw.get("trace", {"total_latency_ms": 1234})
        self.input_tokens = kw.get("input_tokens", 1000)
        self.output_tokens = kw.get("output_tokens", 200)
        self.sources = kw.get("sources", [])
        self.visualizations = []
        self.warnings = []
        self.report_opinions = []


class _FakeAgent:
    def __init__(self, result):
        self._result = result
        self.calls: list[dict] = []

    def answer(self, question, **kw):
        self.calls.append({"question": question, **kw})
        return self._result


def test_runner_records_all_required_fields():
    """§7 이 요구하는 기록 항목이 모두 채워져야 한다."""
    case = _case(
        id="run-1",
        gold_sources=[{"source_type": "term", "source_id": "term:PER"}],
    )
    result = _FakeResult(
        tool_calls=[_FakeToolCall("lookup_financial_term")],
        source_ids=["term:PER"],
        sources=[{"source_id": "term:PER", "source_type": "term", "stock_code": None}],
    )
    rec = EvalRunner(_FakeAgent(result)).run(case)

    assert rec.case_id == "run-1"
    assert rec.question == case.question
    assert rec.tool_sequence == ["lookup_financial_term"]
    assert rec.retrieved_ids == ["term:PER"]
    assert rec.total_latency_ms == 1234
    assert rec.model_calls == 2
    assert rec.tool_call_count == 1
    assert rec.cost_usd > 0
    assert rec.stop_reason == "completed"


def test_runner_passes_screen_context_to_agent():
    """화면 문맥(종목·뉴스)이 그대로 Agent 에 전달돼야 한다."""
    case = _case(
        id="ctx-1",
        type="현재 화면 문맥",
        question="어제 주가 어때?",
        required_tools=["get_stock_prices"],
        context={
            "stock_code": "005930",
            "context_source_type": "news_event",
            "context_source_id": "7134",
        },
    )
    agent = _FakeAgent(_FakeResult())
    EvalRunner(agent).run(case)
    sent = agent.calls[0]
    assert sent["stock_code"] == "005930"
    assert sent["source_type"] == "news_event"
    assert sent["source_id"] == "7134"


def test_runner_survives_agent_exception():
    """한 문항이 터져도 실행기는 기록을 남기고 계속 갈 수 있어야 한다."""

    class _Boom:
        def answer(self, *a, **k):
            raise RuntimeError("boom")

    rec = EvalRunner(_Boom()).run(_case())
    assert rec.stop_reason == "runner_error"
    assert rec.error == "RuntimeError"


def test_numeric_sources_only_include_number_bearing_types():
    result = _FakeResult(
        sources=[
            {"source_id": "a", "source_type": "financial"},
            {"source_id": "b", "source_type": "news_event"},
            {"source_id": "c", "source_type": "price"},
        ]
    )
    rec = EvalRunner(_FakeAgent(result)).run(_case())
    assert {s["source_id"] for s in rec.numeric_sources} == {"a", "c"}


# ─────────────────────────── recorder ───────────────────────────


class _Req:
    def __init__(self, name, args):
        self.tool_call = {"name": name, "args": args, "id": "1"}
        self.tool_name = name


class _ToolMsg:
    def __init__(self, payload):
        self.content = json.dumps(payload)


def test_recorder_captures_tool_arguments():
    """운영 응답에 없는 Tool 입력 인자를 평가 계층에서 관찰한다."""
    rec = ToolCallRecorder()
    rec.wrap_tool_call(
        _Req("get_stock_prices", {"stock_code": "005930"}),
        lambda r: _ToolMsg({"status": "ok"}),
    )
    assert rec.calls[0].name == "get_stock_prices"
    assert rec.calls[0].args == {"stock_code": "005930"}
    assert rec.calls[0].status == "ok"


def test_recorder_records_error_and_reraises():
    rec = ToolCallRecorder()

    def boom(_):
        raise ValueError("x")

    with pytest.raises(ValueError):
        rec.wrap_tool_call(_Req("search_news", {}), boom)
    assert rec.calls[0].status == "error"


# ─────────────────────────── 채점기 ───────────────────────────


def _record(**kw):
    from app.eval.runner import RunRecord

    # 정상 완료가 기본값이어야 채점 경로가 실제 운영과 같아진다
    # (stop_reason 이 비어 있으면 '실행 실패'로 간주돼 채점이 우회된다).
    base = {"case_id": "t-1", "question": "q", "context": {}, "stop_reason": "completed"}
    base.update(kw)
    return RunRecord(**base)


def test_grade_detects_forbidden_tool():
    case = _case(required_tools=["search_news"], forbidden_tools=["get_financial_facts"])
    rec = _record(
        tool_calls=[
            {"name": "search_news", "args": {}, "status": "ok", "latency_ms": 1},
            {"name": "get_financial_facts", "args": {}, "status": "ok", "latency_ms": 1},
        ]
    )
    g = grade_case(case, rec)
    assert g.forbidden_violated == ["get_financial_facts"]


def test_grade_arguments_exact_and_contains():
    """종목코드는 정확 일치, `_contains` 는 부분 일치로 채점한다."""
    case = _case(
        expected_args={
            "search_news": {"stock_code": "005930", "query_contains": "실적"},
        },
        required_tools=["search_news"],
    )
    rec = _record(
        tool_calls=[
            {
                "name": "search_news",
                "args": {"stock_code": "005930", "query": "삼성전자 실적 관련 뉴스"},
                "status": "ok",
                "latency_ms": 1,
            }
        ]
    )
    res = grade_arguments(case, rec)
    assert res == {"search_news.stock_code": True, "search_news.query_contains": True}


def test_grade_arguments_marks_wrong_stock_code():
    case = _case(
        expected_args={"search_news": {"stock_code": "005930"}}, required_tools=["search_news"]
    )
    rec = _record(
        tool_calls=[
            {
                "name": "search_news",
                "args": {"stock_code": "000660"},
                "status": "ok",
                "latency_ms": 1,
            }
        ]
    )
    assert grade_arguments(case, rec)["search_news.stock_code"] is False


def test_grade_arguments_skipped_when_args_unobserved():
    """recorder 없이 실행하면 인자 채점을 건너뛴다(0점 처리하지 않음)."""
    case = _case(
        expected_args={"search_news": {"stock_code": "005930"}}, required_tools=["search_news"]
    )
    rec = _record(
        tool_calls=[{"name": "search_news", "args": None, "status": "ok", "latency_ms": None}]
    )
    assert grade_arguments(case, rec) == {}


def test_grade_detects_other_stock_contamination():
    case = _case(stock_code="005930", required_tools=["search_news"])
    rec = _record(
        tool_calls=[{"name": "search_news", "args": {}, "status": "ok", "latency_ms": 1}],
        sources=[{"source_id": "x", "source_type": "news_event", "stock_code": "000660"}],
    )
    assert grade_case(case, rec).other_stock_sources == ["x"]


def test_grade_unanswerable_pass_and_fail():
    """데이터 없음을 밝히면 통과, 근거 없이 답을 만들면 실패."""
    case = _case(
        id="na-1",
        type="답변 불가능·모호",
        is_answerable=False,
        required_tools=[],
        no_data_expectation="없다고 밝혀야 함",
    )
    ok = grade_case(case, _record(answer="해당 데이터는 없습니다.", sources=[]))
    assert ok.unanswerable_handled is True

    bad = grade_case(case, _record(answer="내년 매출은 300조원입니다.", sources=[]))
    assert bad.unanswerable_handled is False


def test_grade_exclusion_violation():
    case = _case(forbidden_claims=["목표주가"], required_tools=["get_stock_prices"])
    g = grade_case(case, _record(answer="목표주가는 56만원입니다"))
    assert g.exclusion_violations == ["목표주가"]


def test_exclusion_not_violated_when_answer_says_it_excluded():
    """'실적 관련 내용은 제외했습니다'는 제외 조건을 지킨 것이지 위반이 아니다."""
    case = _case(forbidden_claims=["실적"], required_tools=["search_news"])
    g = grade_case(
        case,
        _record(answer="최근 호재 뉴스입니다. 실적 관련 내용은 제외했습니다."),
    )
    assert g.exclusion_violations == []


def test_exclusion_not_violated_when_data_absent():
    """'확정값은 없어 확인할 수 없습니다'도 금지 주장을 한 것이 아니다."""
    case = _case(
        id="na-x",
        type="답변 불가능·모호",
        is_answerable=False,
        required_tools=[],
        no_data_expectation="없다고 밝혀야 함",
        forbidden_claims=["확정"],
    )
    g = grade_case(
        case, _record(answer="내년 매출 확정값은 제공된 데이터가 없어 확인할 수 없습니다.")
    )
    assert g.exclusion_violations == []


def test_exclusion_violation_still_caught_in_other_sentence():
    """다른 문장에서 실제로 금지 내용을 말하면 잡아야 한다(부정문에 숨지 않게)."""
    case = _case(forbidden_claims=["목표주가"], required_tools=["get_stock_prices"])
    g = grade_case(
        case,
        _record(answer="목표주가는 56만원입니다. 일부 자료는 제외했습니다."),
    )
    assert g.exclusion_violations == ["목표주가"]


def test_grade_trading_day_accepts_korean_date_format():
    case = _case(
        required_tools=["get_stock_prices"],
        expected_period={"start_trading_day": "2026-07-24"},
    )
    assert grade_case(case, _record(answer="7월 24일 종가 기준입니다")).trading_day_ok is True
    assert grade_case(case, _record(answer="2026-07-24 종가")).trading_day_ok is True
    assert grade_case(case, _record(answer="7월 25일 종가")).trading_day_ok is False


class _FakeFacts:
    """FactsService 대역 — run_get_financial_facts 가 쓰는 조회만 흉내낸다."""


def test_financial_grade_uses_db_value_not_label(monkeypatch):
    """정답 숫자는 라벨이 아니라 DB 기준행에서 온다."""
    import app.agent.tools.financials as fin_mod

    gold = {
        "value_won": 43_601_051_000_000,
        "unit": "원",
        "period": "2025년 사업보고서 누적",
        "value_kind": "actual_value",
    }

    class _Res:
        status = "ok"
        data = {"facts": [gold]}

    monkeypatch.setattr(fin_mod, "run_get_financial_facts", lambda *a, **k: _Res())

    case = _case(
        id="fin-x",
        type="정확한 재무 숫자",
        question="삼성전자 2025년 연간 누적 영업이익은?",
        required_tools=["get_financial_facts"],
        expected_financial={
            "stock_code": "005930",
            "account_name": "영업이익",
            "business_year": "2025",
            "report_period": "annual",
            "amount_type": "cumulative",
        },
    )
    rec = _record(answer="2025년 연간 누적 영업이익은 43조 6,010억원입니다.")
    g = grade_case(case, rec, _FakeFacts())

    assert g.financial_grade["exact"] is True
    assert g.financial_grade["period_ok"] is True
    assert g.financial_grade["gold_value_won"] == 43_601_051_000_000

    # 틀린 숫자는 잡아야 한다
    bad = grade_case(
        case, _record(answer="2025년 연간 누적 영업이익은 12조원입니다."), _FakeFacts()
    )
    assert bad.financial_grade["exact"] is False


def test_financial_grade_skipped_without_facts_service():
    """오프라인 채점에서는 재무 항목을 건너뛴다(0점 처리하지 않음)."""
    case = _case(
        id="fin-y",
        type="정확한 재무 숫자",
        question="영업이익?",
        required_tools=["get_financial_facts"],
        expected_financial={"stock_code": "005930", "account_name": "영업이익"},
    )
    assert grade_case(case, _record(answer="43조원")).financial_grade is None


def test_aggregate_computes_core_metrics():
    cases = [
        _case(id="a", required_tools=["search_news"], forbidden_tools=["get_financial_facts"]),
        _case(id="b", required_tools=["search_news"]),
    ]
    recs = [
        _record(
            case_id="a",
            tool_calls=[{"name": "search_news", "args": {}, "status": "ok", "latency_ms": 5}],
            answer="답변 [1]",
            sources=[{"source_id": "s1", "source_type": "news_event"}],
            total_latency_ms=100,
            model_calls=2,
        ),
        _record(
            case_id="b",
            tool_calls=[
                {"name": "get_financial_facts", "args": {}, "status": "ok", "latency_ms": 5}
            ],
            answer="답변",
            sources=[],
            total_latency_ms=300,
            model_calls=3,
        ),
    ]
    grades = [grade_case(c, r) for c, r in zip(cases, recs, strict=True)]
    agg = aggregate(cases, recs, grades)

    assert agg["n"] == 2
    # a 만 search_news 호출 → 2건 중 1건
    assert agg["agent"]["required_tool_recall"] == 0.5
    assert agg["ops"]["avg_model_calls"] == 2.5
    # b 는 출처가 없다 → coverage 1/2
    assert agg["answer"]["citation_coverage"] == 0.5


def test_unmeasured_metric_is_none_not_zero():
    """측정 대상이 없으면 0.0(전부 틀림)이 아니라 None(못 잼)이어야 한다."""
    case = _case(id="m", required_tools=["lookup_financial_term"])
    rec = _record(
        case_id="m",
        tool_calls=[{"name": "lookup_financial_term", "args": {}, "status": "ok", "latency_ms": 1}],
        answer="설명입니다",
        sources=[{"source_id": "term:PER", "source_type": "term"}],
    )
    agg = aggregate([case], [rec], [grade_case(case, rec)])
    # 이 케이스엔 기대 숫자·정답 식별자가 없다 → 잰 적 없음
    assert agg["numbers"]["number_exact_match"] is None
    assert agg["retrieval"]["document_retrieval"]["mrr"] is None


def test_document_retrieval_and_structured_lookup_are_separated():
    """문서 검색(순위)과 구조화 조회(정확 행)는 성격이 달라 따로 집계해야 한다."""
    doc_case = _case(
        id="d",
        type="뉴스 사건·영향",
        question="무슨 일 있었어?",
        stock_code="005930",
        required_tools=["search_news"],
        gold_sources=[{"source_type": "news_event", "source_id": "chunk-1"}],
    )
    lookup_case = _case(
        id="l",
        gold_sources=[{"source_type": "term", "source_id": "term:PER"}],
    )
    doc_rec = _record(
        case_id="d",
        tool_calls=[{"name": "search_news", "args": {}, "status": "ok", "latency_ms": 1}],
        retrieved_ids=["chunk-1"],
        answer="사건 설명",
        sources=[{"source_id": "chunk-1", "source_type": "news_event", "stock_code": "005930"}],
    )
    lookup_rec = _record(
        case_id="l",
        tool_calls=[{"name": "lookup_financial_term", "args": {}, "status": "ok", "latency_ms": 1}],
        retrieved_ids=[],  # 정답 행을 못 집음
        answer="설명",
        sources=[],
    )
    cases = [doc_case, lookup_case]
    recs = [doc_rec, lookup_rec]
    grades = [grade_case(c, r) for c, r in zip(cases, recs, strict=True)]
    agg = aggregate(cases, recs, grades)

    # 문서 검색은 맞혔고, 구조화 조회는 틀렸다 — 한 숫자로 섞이지 않아야 한다.
    assert agg["retrieval"]["document_retrieval"]["recall_at_k"] == 1.0
    assert agg["retrieval"]["structured_lookup"]["row_hit_rate"] == 0.0


def test_validator_dropped_answer_not_counted_as_retriever_failure():
    """Tool 이 정답 문서를 반환했는데 검증기가 지운 경우는 검색 실패가 아니다(§4)."""
    case = _case(
        id="r",
        type="증권사 리포트",
        question="목표주가 얼마야?",
        stock_code="005930",
        required_tools=["search_research_reports"],
        gold_sources=[{"source_type": "research_report", "source_id": "rc-1"}],
    )
    rec = _record(
        case_id="r",
        tool_calls=[
            {"name": "search_research_reports", "args": {}, "status": "ok", "latency_ms": 1}
        ],
        retrieved_ids=["rc-other"],
        answer="일부 목표주가를 확인할 수 없어 제외했습니다.",
        sources=[{"source_id": "rc-other", "source_type": "research_report"}],
        validation_errors=["근거 없는 증권사·목표주가 문장을 답변에서 제거함"],
    )
    agg = aggregate([case], [rec], [grade_case(case, rec)])
    # 분모에 들어가지 않아 '미측정'이어야 한다(0.0 으로 검색 탓을 하지 않는다).
    assert agg["retrieval"]["document_retrieval"]["recall_at_k"] is None


def test_other_stock_source_still_counts_as_retrieval_failure():
    """다른 종목을 반환한 경우는 계속 검색 실패로 남아야 한다."""
    case = _case(
        id="x",
        type="뉴스 사건·영향",
        question="무슨 일 있었어?",
        stock_code="005930",
        required_tools=["search_news"],
        gold_sources=[{"source_type": "news_event", "source_id": "chunk-1"}],
    )
    rec = _record(
        case_id="x",
        tool_calls=[{"name": "search_news", "args": {}, "status": "ok", "latency_ms": 1}],
        retrieved_ids=["chunk-9"],
        answer="다른 종목 뉴스",
        sources=[{"source_id": "chunk-9", "source_type": "news_event", "stock_code": "000660"}],
        validation_errors=["근거 없는 증권사·목표주가 문장을 답변에서 제거함"],
    )
    agg = aggregate([case], [rec], [grade_case(case, rec)])
    assert agg["retrieval"]["document_retrieval"]["recall_at_k"] == 0.0


def test_period_check_does_not_require_words_absent_from_question():
    """'연간 매출액' 질문에 '누적'을 쓰라고 요구하면 안 된다(채점기 오탐)."""
    case = _case(
        id="p",
        type="정확한 재무 숫자",
        question="삼성전자 2025년 연간 매출액 알려줘",
        required_tools=["get_financial_facts"],
        expected_period={"business_year": "2025", "amount_type": "누적"},
    )
    rec = _record(answer="삼성전자의 2025년 연간 매출액은 333.61조원입니다.")
    assert grade_case(case, rec).period_ok is True


def test_period_check_still_catches_wrong_year():
    case = _case(
        id="p2",
        type="정확한 재무 숫자",
        question="삼성전자 2025년 연간 매출액 알려줘",
        required_tools=["get_financial_facts"],
        expected_period={"business_year": "2025"},
    )
    rec = _record(answer="삼성전자의 2024년 연간 매출액은 300조원입니다.")
    assert grade_case(case, rec).period_ok is False


def test_aggregate_counts_validation_errors_as_metrics():
    case = _case(id="v", required_tools=["search_news"])
    rec = _record(
        case_id="v",
        tool_calls=[{"name": "search_news", "args": {}, "status": "ok", "latency_ms": 1}],
        answer="답변 [3]",
        sources=[{"source_id": "s", "source_type": "news_event"}],
        validation_errors=["존재하지 않는 인용 번호: [3] (근거 출처 1개)"],
    )
    agg = aggregate([case], [rec], [grade_case(case, rec)])
    assert agg["answer"]["nonexistent_citations"] == 1
    assert agg["answer"]["citation_precision"] == 0.0
