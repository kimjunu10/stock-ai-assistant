"""Canonical news cluster Gold and execution-time resolution tests."""

from __future__ import annotations

from app.eval.grader import document_recall_stats, grade_case
from app.eval.news_gold import resolve_news_gold_rows
from app.eval.runner import RunRecord
from app.eval.schema import EvalCase


def _case(cluster_id: str = "7108") -> EvalCase:
    return EvalCase(
        id="h-news-x",
        type="뉴스 사건·영향",
        question="SK하이닉스 이재명 대통령 이슈 설명해줘",
        stock_code="000660",
        required_tools=["search_news"],
        gold_sources=[
            {
                "source_type": "news_event",
                "source_id": None,
                "canonical_id": f"news_clusters.id={cluster_id}",
                "ref": "이재명 대통령 방미 계기 AI 협력",
            }
        ],
    )


def _cluster(cluster_id: str = "7108") -> dict:
    return {
        "id": int(cluster_id),
        "stock_code": "000660",
        "summary_title": "이재명 대통령 방미 계기 AI 협력",
        "first_published_at": "2026-07-24T11:13:00+00:00",
    }


def _document(cluster_id: str = "7108") -> dict:
    return {
        "id": "new-document-id",
        "source_pk": cluster_id,
        "stock_code": "000660",
        "is_current": True,
    }


def _chunk(cluster_id: str = "7108") -> dict:
    return {
        "id": "new-chunk-id",
        "document_id": "new-document-id",
        "stock_code": "000660",
        "is_active": True,
        "source_locator": {"cluster_id": int(cluster_id)},
    }


def _source(cluster_id: str) -> dict:
    return {
        "source_id": f"runtime-chunk-{cluster_id}",
        "source_type": "news_event",
        "stock_code": "000660",
        "locator": {"source_pk": cluster_id},
    }


def test_reindexed_chunk_in_same_cluster_resolves() -> None:
    result = resolve_news_gold_rows(
        [_case()],
        cluster_rows=[_cluster()],
        document_rows=[_document()],
        chunk_rows=[_chunk()],
    )

    assert result["should_abort"] is False
    assert result["resolutions"][0]["canonical_id"] == "news_clusters.id=7108"
    assert result["resolutions"][0]["resolved_document_id"] == "new-document-id"
    assert result["resolutions"][0]["resolved_chunk_ids"] == ["new-chunk-id"]


def test_resolved_chunk_from_different_cluster_aborts() -> None:
    result = resolve_news_gold_rows(
        [_case()],
        cluster_rows=[_cluster()],
        document_rows=[_document()],
        chunk_rows=[_chunk("9999")],
    )

    assert result["should_abort"] is True
    assert result["errors"][0]["reason"] == "resolved_chunk_cluster_mismatch"


def test_missing_canonical_cluster_aborts() -> None:
    result = resolve_news_gold_rows(
        [_case()],
        cluster_rows=[],
        document_rows=[],
        chunk_rows=[],
    )

    assert result["should_abort"] is True
    assert result["errors"][0]["reason"] == "canonical_cluster_missing"


def test_missing_current_active_chunk_aborts() -> None:
    result = resolve_news_gold_rows(
        [_case()],
        cluster_rows=[_cluster()],
        document_rows=[_document()],
        chunk_rows=[],
    )

    assert result["should_abort"] is True
    assert result["errors"][0]["reason"] == "current_active_chunk_missing"


def test_strict_retrieval_hits_canonical_cluster_after_reindex() -> None:
    case = _case()
    record = RunRecord(
        case_id=case.id,
        question=case.question,
        context={},
        sources=[_source("7108")],
        stop_reason="completed",
    )
    grade = grade_case(case, record)

    stats = document_recall_stats([case], [record], [grade], "news_event")

    assert stats["recall_at_k"] == 1.0
    assert stats["hit_at_1"] == 1.0
    assert stats["mrr"] == 1.0


def test_strict_retrieval_preserves_actual_cluster_ranking_for_hit1_and_mrr() -> None:
    case = _case()
    record = RunRecord(
        case_id=case.id,
        question=case.question,
        context={},
        sources=[_source("9999"), _source("7108"), _source("8888")],
        stop_reason="completed",
    )
    grade = grade_case(case, record)

    stats = document_recall_stats([case], [record], [grade], "news_event")

    assert stats["recall_at_k"] == 1.0
    assert stats["hit_at_1"] == 0.0
    assert stats["mrr"] == 0.5
