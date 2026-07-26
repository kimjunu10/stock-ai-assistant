"""Phase 8 지표 감사(phase/8-metric-audit) 단위 테스트. LLM·DB 호출 없음.

문서 검색 recall/hit@1/mrr 를 부모 문서 ID 기준으로, 뉴스/리포트를 분리해
재계산하는 aggregate() 를 검증한다. 청크 ID 합산 대신 문서 단위로 비교해야
하는 이유(같은 문서의 다른 청크를 반환해도 적중)와, 구조화 조회·Validator
실패가 문서 검색 실패로 잘못 세지지 않아야 한다는 원칙을 각각의 테스트로
고정한다.
"""

from __future__ import annotations

from app.eval.grader import document_ranking, grade_case
from app.eval.metrics import _ratio
from app.eval.runner import RunRecord
from app.eval.schema import EvalCase


def _case(**kw) -> EvalCase:
    base = {
        "id": "t-1",
        "type": "뉴스 사건·영향",
        "question": "무슨 일 있었어?",
        "stock_code": "005930",
        "required_tools": ["search_news"],
    }
    base.update(kw)
    return EvalCase(**base)


def _record(**kw) -> RunRecord:
    base = {"case_id": "t-1", "question": "q", "context": {}, "stop_reason": "completed"}
    base.update(kw)
    return RunRecord(**base)


def _news_gold(cluster_id: str, chunk_id: str = "chunk-1") -> list[dict]:
    return [
        {
            "source_type": "news_event",
            "source_id": chunk_id,
            "note": f"news_clusters.id={cluster_id}",
        }
    ]


def _report_gold(report_id: str, chunk_id: str = "rc-1") -> list[dict]:
    return [
        {
            "source_type": "research_report",
            "source_id": chunk_id,
            "note": f"research_reports.id={report_id}",
        }
    ]


def _news_source(cluster_id: str, chunk_id: str, stock_code: str = "005930") -> dict:
    return {
        "source_id": chunk_id,
        "source_type": "news_event",
        "stock_code": stock_code,
        "locator": {"source_pk": cluster_id},
    }


def _report_source(report_id: str, chunk_id: str, stock_code: str = "005930") -> dict:
    return {
        "source_id": chunk_id,
        "source_type": "research_report",
        "stock_code": stock_code,
        "locator": {"report_id": report_id},
    }


def test_gold_document_ranked_first():
    """gold 문서가 1위 결과일 때 recall/hit@1/mrr 모두 만점이어야 한다."""
    from app.eval.grader import aggregate

    case = _case(id="n1", gold_sources=_news_gold("9001"))
    rec = _record(
        case_id="n1",
        tool_calls=[{"name": "search_news", "args": {}, "status": "ok", "latency_ms": 1}],
        sources=[_news_source("9001", "c1"), _news_source("9002", "c2")],
    )
    assert document_ranking(rec)[0] == "news:9001"
    agg = aggregate([case], [rec], [grade_case(case, rec)])
    stats = agg["retrieval"]["news_retrieval"]
    assert stats["recall_at_k"] == 1.0
    assert stats["hit_at_1"] == 1.0
    assert stats["mrr"] == 1.0


def test_gold_document_ranked_within_k_but_not_first():
    """gold 문서가 K 이내 후순위(2위 이상)면 recall 은 맞지만 hit@1 은 아니다."""
    from app.eval.grader import aggregate

    case = _case(id="n1", gold_sources=_news_gold("9002"))
    rec = _record(
        case_id="n1",
        tool_calls=[{"name": "search_news", "args": {}, "status": "ok", "latency_ms": 1}],
        sources=[_news_source("9001", "c1"), _news_source("9002", "c2")],
    )
    ranking = document_ranking(rec)
    assert ranking.index("news:9002") == 1  # 2위(0-index 1) — 1위가 아님
    agg = aggregate([case], [rec], [grade_case(case, rec)])
    stats = agg["retrieval"]["news_retrieval"]
    assert stats["recall_at_k"] == 1.0  # K(=반환 개수) 이내에는 있음
    assert stats["hit_at_1"] == 0.0  # 1위는 아님
    assert stats["mrr"] == 0.5  # 2위 → 1/2


def test_gold_document_absent():
    """gold 문서가 반환 결과에 전혀 없으면 미스로 남는다."""
    from app.eval.grader import aggregate

    case = _case(id="n1", gold_sources=_news_gold("9999"))
    rec = _record(
        case_id="n1",
        tool_calls=[{"name": "search_news", "args": {}, "status": "ok", "latency_ms": 1}],
        sources=[_news_source("9001", "c1")],
    )
    assert "news:9999" not in document_ranking(rec)
    agg = aggregate([case], [rec], [grade_case(case, rec)])
    stats = agg["retrieval"]["news_retrieval"]
    assert stats["recall_at_k"] == 0.0
    assert stats["hit_at_1"] == 0.0
    assert stats["mrr"] == 0.0
    assert stats["missed_case_ids"] == ["n1"]


def test_duplicate_chunks_of_same_parent_document_count_once():
    """같은 부모 문서의 청크가 여러 개 반환돼도 순위 목록엔 문서 1건으로 축약된다."""
    rec = _record(
        tool_calls=[{"name": "search_news", "args": {}, "status": "ok", "latency_ms": 1}],
        sources=[
            _news_source("9001", "c1"),
            _news_source("9001", "c2"),  # 같은 사건(9001)의 다른 청크
            _news_source("9003", "c3"),
        ],
    )
    ranking = document_ranking(rec)
    assert ranking == ["news:9001", "news:9003"]  # 중복 없이 1건으로 축약, 순서 유지


def test_validator_dropped_answer_counts_as_document_hit():
    """검색은 정답 문서를 반환했는데 Validator 가 답변만 지운 경우는 검색 적중이다."""
    from app.eval.grader import aggregate

    case = _case(
        id="r1",
        type="증권사 리포트",
        required_tools=["search_research_reports"],
        gold_sources=_report_gold("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
    )
    rec = _record(
        case_id="r1",
        tool_calls=[
            {"name": "search_research_reports", "args": {}, "status": "ok", "latency_ms": 1}
        ],
        # 답변이 지워지는 상황에서도 sources 는 Tool 이 실제로 찾은 문서를 담고 있다.
        sources=[_report_source("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa", "rc-other")],
        answer="일부 목표주가를 확인할 수 없어 제외했습니다.",
        validation_errors=["근거 없는 증권사·목표주가 문장을 답변에서 제거함"],
    )
    agg = aggregate([case], [rec], [grade_case(case, rec)])
    assert agg["retrieval"]["report_retrieval"]["recall_at_k"] == 1.0


def test_news_and_report_are_evaluated_and_reported_separately():
    """뉴스/리포트가 한 실행에 섞여 있어도 각자 다른 분모로 별도 집계돼야 한다."""
    from app.eval.grader import aggregate

    news_case = _case(id="n1", gold_sources=_news_gold("9001"))
    report_id = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    report_case = _case(id="r1", type="증권사 리포트", gold_sources=_report_gold(report_id))
    news_rec = _record(
        case_id="n1",
        tool_calls=[{"name": "search_news", "args": {}, "status": "ok", "latency_ms": 1}],
        sources=[_news_source("9001", "c1")],
    )
    report_tool_call = {
        "name": "search_research_reports",
        "args": {},
        "status": "ok",
        "latency_ms": 1,
    }
    report_rec = _record(
        case_id="r1",
        tool_calls=[report_tool_call],
        sources=[],  # 리포트는 못 찾음
    )
    cases, recs = [news_case, report_case], [news_rec, report_rec]
    grades = [grade_case(c, r) for c, r in zip(cases, recs, strict=True)]
    agg = aggregate(cases, recs, grades)

    assert agg["retrieval"]["news_retrieval"]["n_eval"] == 1
    assert agg["retrieval"]["news_retrieval"]["recall_at_k"] == 1.0
    assert agg["retrieval"]["report_retrieval"]["n_eval"] == 1
    assert agg["retrieval"]["report_retrieval"]["recall_at_k"] == 0.0


def test_structured_lookup_question_excluded_from_document_retrieval_denominator():
    """구조화 조회(term/financial/disclosure) 질문은 문서 검색 분모에 들어가지 않는다."""
    from app.eval.grader import aggregate

    term_case = _case(
        id="term-1",
        type="금융용어",
        required_tools=["lookup_financial_term"],
        gold_sources=[{"source_type": "term", "source_id": "term:PER"}],
    )
    rec = _record(
        case_id="term-1",
        tool_calls=[{"name": "lookup_financial_term", "args": {}, "status": "ok", "latency_ms": 1}],
        sources=[{"source_id": "term:PER", "source_type": "term"}],
    )
    agg = aggregate([term_case], [rec], [grade_case(term_case, rec)])
    # 뉴스/리포트 어느 쪽 분모에도 이 문항이 들어가지 않아 n_eval=0(미측정=None).
    assert agg["retrieval"]["news_retrieval"]["n_eval"] == 0
    assert agg["retrieval"]["report_retrieval"]["n_eval"] == 0
    assert agg["retrieval"]["news_retrieval"]["recall_at_k"] is None
    assert agg["retrieval"]["report_retrieval"]["recall_at_k"] is None
    assert agg["retrieval"]["structured_lookup"]["row_hit_rate"] == 1.0


def test_required_tools_all_called_vs_one_missing():
    """필수 Tool 이 모두 호출된 경우와 하나 누락된 경우를 정확한 분모로 구분한다."""
    from app.eval.grader import aggregate

    case_ok = _case(id="ok", required_tools=["search_news", "get_stock_prices"])
    case_missing = _case(id="missing", required_tools=["search_news", "get_stock_prices"])
    rec_ok = _record(
        case_id="ok",
        tool_calls=[
            {"name": "search_news", "args": {}, "status": "ok", "latency_ms": 1},
            {"name": "get_stock_prices", "args": {}, "status": "ok", "latency_ms": 1},
        ],
    )
    rec_missing = _record(
        case_id="missing",
        tool_calls=[{"name": "search_news", "args": {}, "status": "ok", "latency_ms": 1}],
    )
    cases = [case_ok, case_missing]
    recs = [rec_ok, rec_missing]
    grades = [grade_case(c, r) for c, r in zip(cases, recs, strict=True)]
    agg = aggregate(cases, recs, grades)

    # 분모 4(2문항 x 2 Tool), 분자 3(missing 문항은 search_news 만 성공).
    assert agg["agent"]["required_tool_recall"] == _ratio(3, 4)
    assert grades[0].passed_required_tools is True
    assert grades[1].passed_required_tools is False
