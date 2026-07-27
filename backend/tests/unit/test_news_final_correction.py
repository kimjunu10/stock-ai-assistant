"""Phase 8 뉴스 최종 교정(phase/8-news-final-correction) 단위 테스트. LLM·DB 호출 없음.

§3 상대 날짜 평가 계약(evaluation_run_at 기준 stale_gold 분류)과 §4 지표 분리
(strict / event-equivalent / product failure)를 검증한다. strict 지표는 항상
그대로 보존되고(삭제·숨김 없음), event-equivalent·product-failure 는 추가
필드로만 존재해야 한다는 원칙을 각각의 테스트로 고정한다.
"""

from __future__ import annotations

import json
from datetime import datetime

from app.eval.grader import (
    aggregate,
    event_equivalent_recall_stats,
    gold_out_of_relative_range,
    grade_case,
    load_event_equivalent_approvals,
    preflight_check_relative_gold_validity,
    product_failure_stats,
)
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


def _news_gold(cluster_id: str, published: str, chunk_id: str = "chunk-1") -> list[dict]:
    return [
        {
            "source_type": "news_event",
            "source_id": chunk_id,
            "note": f"news_clusters.id={cluster_id} / {published} / positive / 기사 1건",
        }
    ]


def _news_source(cluster_id: str, chunk_id: str, stock_code: str = "005930") -> dict:
    return {
        "source_id": chunk_id,
        "source_type": "news_event",
        "stock_code": stock_code,
        "locator": {"source_pk": cluster_id},
    }


def _search_news_call(relative_period: str | None = "recent") -> dict:
    args = {"stock_code": "005930"}
    if relative_period:
        args["relative_period"] = relative_period
    return {"name": "search_news", "args": args, "status": "ok", "latency_ms": 1}


class TestStaleGoldClassification:
    def test_gold_within_relative_range_is_not_stale(self):
        """gold 발행일이 실행 시각 기준 recent(2일 lookback) 범위 안이면 stale 아니다."""
        case = _case(gold_sources=_news_gold("9001", "2026-07-25"))
        rec = _record(
            tool_calls=[_search_news_call("recent")],
            sources=[],
            evaluation_run_at="2026-07-27T00:49:00+09:00",
        )
        assert gold_out_of_relative_range(case, rec) is False

    def test_gold_outside_relative_range_is_stale(self):
        """gold 발행일이 실행 시각 기준 범위 밖이면 stale_gold(평가 데이터 문제)다."""
        case = _case(gold_sources=_news_gold("9001", "2026-07-22"))
        rec = _record(
            tool_calls=[_search_news_call("recent")],
            sources=[],
            evaluation_run_at="2026-07-27T00:49:00+09:00",
        )
        assert gold_out_of_relative_range(case, rec) is True

    def test_no_evaluation_run_at_never_classified_stale(self):
        """evaluation_run_at 이 없는 과거 저장 기록은 판정 불가로 두고 False(=제품
        실패 쪽에 남김)로 처리한다 — 소급 적용하지 않는다."""
        case = _case(gold_sources=_news_gold("9001", "2026-07-22"))
        rec = _record(tool_calls=[_search_news_call("recent")], sources=[], evaluation_run_at=None)
        assert gold_out_of_relative_range(case, rec) is False

    def test_absolute_date_search_not_treated_as_relative(self):
        """date_from/date_to 로 절대 날짜를 지정한 호출은 상대 기간 계약과 무관하다."""
        case = _case(gold_sources=_news_gold("9001", "2026-07-22"))
        rec = _record(
            tool_calls=[
                {
                    "name": "search_news",
                    "args": {"stock_code": "005930", "date_from": "2026-07-01"},
                    "status": "ok",
                    "latency_ms": 1,
                }
            ],
            sources=[],
            evaluation_run_at="2026-07-27T00:49:00+09:00",
        )
        assert gold_out_of_relative_range(case, rec) is False


class TestEventEquivalentRecall:
    def test_strict_miss_but_approved_equivalent_hit_counts(self):
        """strict gold 는 놓쳤지만 사람이 승인한 동일 사건 클러스터를 반환했으면
        event-equivalent Recall 은 적중으로 센다(strict 는 그대로 미스로 남는다)."""
        case = _case(id="news-x", gold_sources=_news_gold("6974", "2026-07-24"))
        rec = _record(
            case_id="news-x",
            tool_calls=[_search_news_call()],
            sources=[_news_source("7222", "c1")],
        )
        grade = grade_case(case, rec)
        approvals = {"news-x": ["news:7222"]}

        strict_hit = "news:6974" in [s.get("locator", {}).get("source_pk") for s in rec.sources]
        assert not strict_hit  # strict 는 여전히 미스

        stats = event_equivalent_recall_stats([case], [rec], [grade], "news_event", approvals)
        assert stats["recall_hit"] == 1
        assert stats["recall_at_k"] == 1.0
        assert stats["missed_case_ids"] == []

    def test_unapproved_alternative_cluster_does_not_count(self):
        """승인 매핑에 없는 클러스터는 아무리 같은 종목이어도 event-equivalent 적중이
        아니다(자동 승인 금지 원칙)."""
        case = _case(id="news-x", gold_sources=_news_gold("6974", "2026-07-24"))
        rec = _record(
            case_id="news-x",
            tool_calls=[_search_news_call()],
            sources=[_news_source("9999", "c1")],
        )
        grade = grade_case(case, rec)
        stats = event_equivalent_recall_stats([case], [rec], [grade], "news_event", approvals={})
        assert stats["recall_hit"] == 0
        assert stats["missed_case_ids"] == ["news-x"]

    def test_other_stock_contamination_not_forgiven_by_approval(self):
        """승인된 대체 문서를 반환했어도 다른 종목이 섞여 있으면 여전히 실패다."""
        case = _case(
            id="news-x", stock_code="005930", gold_sources=_news_gold("6974", "2026-07-24")
        )
        rec = _record(
            case_id="news-x",
            tool_calls=[_search_news_call()],
            sources=[_news_source("7222", "c1", stock_code="000660")],
        )
        grade = grade_case(case, rec)
        approvals = {"news-x": ["news:7222"]}
        stats = event_equivalent_recall_stats([case], [rec], [grade], "news_event", approvals)
        assert stats["recall_hit"] == 0
        assert stats["missed_case_ids"] == ["news-x"]


class TestProductFailureRate:
    def test_tool_not_called_is_product_failure(self):
        """필수 Tool(search_news) 자체를 안 부르면 무조건 제품 실패다."""
        case = _case(id="news-x", gold_sources=_news_gold("6974", "2026-07-24"))
        rec = _record(case_id="news-x", tool_calls=[], sources=[])
        grade = grade_case(case, rec)
        stats = product_failure_stats([case], [rec], [grade], "news_event")
        assert stats["failures"] == 1
        assert stats["failed_case_ids"] == ["news-x"]

    def test_stale_gold_miss_excluded_from_product_failure(self):
        """gold 가 실행 시각 기준 상대 기간 범위 밖(stale_gold)이면 검색을 놓쳤어도
        제품 실패로 세지 않는다(§4D 평가 데이터 문제로 분류)."""
        case = _case(id="news-x", gold_sources=_news_gold("6974", "2026-07-22"))
        rec = _record(
            case_id="news-x",
            tool_calls=[_search_news_call("recent")],
            sources=[],
            evaluation_run_at="2026-07-27T00:49:00+09:00",
        )
        grade = grade_case(case, rec)
        stats = product_failure_stats([case], [rec], [grade], "news_event")
        assert stats["failures"] == 0
        assert stats["failed_case_ids"] == []

    def test_genuine_retriever_miss_still_counted(self):
        """상대 기간과 무관하게 gold 가 범위 안인데도 못 찾았으면 제품 실패로 남는다."""
        case = _case(id="news-x", gold_sources=_news_gold("6974", "2026-07-26"))
        rec = _record(
            case_id="news-x",
            tool_calls=[_search_news_call("recent")],
            sources=[],
            evaluation_run_at="2026-07-27T00:49:00+09:00",
        )
        grade = grade_case(case, rec)
        stats = product_failure_stats([case], [rec], [grade], "news_event")
        assert stats["failures"] == 1
        assert stats["failed_case_ids"] == ["news-x"]


class TestStrictMetricsPreserved:
    def test_strict_recall_unchanged_when_event_equivalent_added(self):
        """event_equivalent_approvals_path 를 넘겨도 strict news_retrieval 수치는
        그대로다(§4 '기존 strict 지표를 삭제하거나 숨기지 않는다')."""
        case = _case(id="news-x", gold_sources=_news_gold("6974", "2026-07-24"))
        rec = _record(
            case_id="news-x",
            tool_calls=[_search_news_call()],
            sources=[_news_source("7222", "c1")],
        )
        grade = grade_case(case, rec)
        agg_without = aggregate([case], [rec], [grade])
        agg_with = aggregate(
            [case], [rec], [grade], event_equivalent_approvals_path="/nonexistent/path.json"
        )
        assert agg_without["retrieval"]["news_retrieval"] == agg_with["retrieval"]["news_retrieval"]
        assert agg_without["retrieval"]["news_retrieval"]["recall_at_k"] == 0.0


class TestHoldoutPreflight:
    """§3 홀드아웃 정책: 실행 전 상대 날짜 gold 유효성만 미리 점검하는 순수 함수.

    devset 케이스로만 검증한다 — holdout.json 은 이 테스트에서도 열지 않는다.
    """

    def test_gold_within_recent_range_passes(self):
        case = _case(
            id="news-x",
            question="최근 3일 뉴스 알려줘",
            gold_sources=_news_gold("6974", "2026-07-26"),
        )
        result = preflight_check_relative_gold_validity(
            [case], planned_run_at=datetime.fromisoformat("2026-07-27T09:00:00+09:00")
        )
        assert result["n_checked"] == 1
        assert result["n_stale"] == 0
        assert result["should_abort"] is False

    def test_gold_outside_recent_range_flags_abort(self):
        case = _case(
            id="news-x",
            question="최근 뉴스 알려줘",
            gold_sources=_news_gold("6974", "2026-07-20"),
        )
        result = preflight_check_relative_gold_validity(
            [case], planned_run_at=datetime.fromisoformat("2026-07-27T09:00:00+09:00")
        )
        assert result["n_stale"] == 1
        assert result["stale_cases"][0]["case_id"] == "news-x"
        assert result["should_abort"] is True

    def test_news_without_relative_period_is_skipped_even_when_gold_is_old(self):
        case = _case(
            id="news-x",
            question="삼성전자 브로드컴 건은 어떤 내용이야?",
            gold_sources=_news_gold("6974", "2026-07-20"),
        )
        result = preflight_check_relative_gold_validity(
            [case], planned_run_at=datetime.fromisoformat("2026-07-27T09:00:00+09:00")
        )
        assert result["n_checked"] == 0
        assert result["n_skipped_non_relative"] == 1
        assert result["n_stale"] == 0
        assert result["should_abort"] is False

    def test_expected_tool_relative_period_is_checked(self):
        case = _case(
            id="news-x",
            question="삼성전자 뉴스 알려줘",
            expected_args={"search_news": {"relative_period": "last_7_days"}},
            gold_sources=_news_gold("6974", "2026-07-22"),
        )
        result = preflight_check_relative_gold_validity(
            [case], planned_run_at=datetime.fromisoformat("2026-07-27T09:00:00+09:00")
        )
        assert result["n_checked"] == 1
        assert result["n_stale"] == 0
        assert result["should_abort"] is False

    def test_case_without_gold_note_date_is_skipped(self):
        """gold note 에 발행일이 없는(구조화 조회 등) 문항은 점검 대상이 아니다."""
        case = _case(
            id="term-x",
            type="금융용어",
            required_tools=["lookup_financial_term"],
            gold_sources=[{"source_type": "term", "source_id": "term:PER"}],
        )
        result = preflight_check_relative_gold_validity(
            [case], planned_run_at=datetime.fromisoformat("2026-07-27T09:00:00+09:00")
        )
        assert result["n_stale"] == 0
        assert result["should_abort"] is False

    def test_does_not_mutate_or_require_run_records(self):
        """실행 기록(RunRecord) 없이 case 목록만으로 동작한다(실행 전 점검)."""
        case = _case(
            id="news-x",
            question="최근 뉴스 알려줘",
            gold_sources=_news_gold("6974", "2026-07-20"),
        )
        before = case.model_dump()
        preflight_check_relative_gold_validity(
            [case], planned_run_at=datetime.fromisoformat("2026-07-27T09:00:00+09:00")
        )
        assert case.model_dump() == before

    def test_approval_file_loading_uses_case_gold_kind(self, tmp_path):
        """승인 파일 로드시 뉴스/리포트 구분은 case 의 strict gold 문서 종류를 따른다."""
        case = _case(id="news-x", gold_sources=_news_gold("6974", "2026-07-24"))
        approvals_file = tmp_path / "approvals.json"
        approvals_file.write_text(
            json.dumps(
                {"approvals": [{"case_id": "news-x", "approved_equivalent_cluster_ids": ["7222"]}]}
            ),
            encoding="utf-8",
        )
        loaded = load_event_equivalent_approvals(str(approvals_file), [case])
        assert loaded == {"news-x": ["news:7222"]}
