from __future__ import annotations

from typing import Any

import numpy as np

from app.core.config import Settings
from app.services.news_clustering import NewsClusteringService


class FakeEmbedder:
    def __init__(self, vectors: dict[int, list[float]]):
        self.vectors = vectors

    def encode(self, article: dict[str, Any]) -> np.ndarray:
        return np.asarray(self.vectors[int(article["article_id"])], dtype=np.float32)


class MemoryClusterRepository:
    def __init__(self, articles: list[dict[str, Any]]):
        self.articles = {int(row["article_id"]): row for row in articles}
        self.processing: dict[int, dict[str, Any]] = {}
        self.assignments: dict[tuple[int, str], dict[str, Any]] = {}
        self.clusters: dict[int, dict[str, Any]] = {}
        self.summaries: dict[int, dict[str, Any]] = {}
        self.next_cluster_id = 1

    def get_summary_retry_clusters(self, limit: int) -> list[dict[str, Any]]:
        return []

    def get_pipeline_candidates(self, limit: int) -> list[dict[str, Any]]:
        return [
            row
            for article_id, row in self.articles.items()
            if self.processing.get(article_id, {}).get("status") != "completed"
        ][:limit]

    def mark_article_processing(self, article_id: int, kind: str, retry_count: int) -> None:
        self.processing[article_id] = {
            "status": "processing",
            "kind": kind,
            "retry_count": retry_count,
        }

    def mark_article_complete(self, article_id: int, kind: str) -> None:
        self.processing[article_id].update(status="completed", kind=kind)

    def mark_article_retry(self, article_id: int, kind: str, retry_count: int, error: str) -> None:
        self.processing[article_id] = {
            "status": "pending_retry",
            "kind": kind,
            "retry_count": retry_count,
            "last_error": error,
        }
        self.articles[article_id]["retry_count"] = retry_count

    def get_assignment(self, article_id: int, stock_code: str):
        return self.assignments.get((article_id, stock_code))

    def get_active_clusters(self, stock_code: str, kind: str, published_at: str, window_hours=72):
        return [
            row
            for row in self.clusters.values()
            if row["stock_code"] == stock_code and row["kind"] == kind
        ]

    def create_cluster(self, *, article, stock_code, kind, centroid):
        cluster_id = self.next_cluster_id
        self.next_cluster_id += 1
        self.clusters[cluster_id] = {
            "id": cluster_id,
            "stock_code": stock_code,
            "kind": kind,
            "centroid": centroid,
            "article_count": 1,
            "last_active_at": article["published_at"],
            "anchor": {
                "title": article["title"],
                "description": article.get("description", ""),
            },
        }
        return cluster_id

    def update_cluster(self, cluster_id, *, centroid, article_count, last_active_at):
        self.clusters[cluster_id].update(
            centroid=centroid,
            article_count=article_count,
            last_active_at=last_active_at,
        )

    def save_assignment(self, **payload):
        self.assignments[(payload["article_id"], payload["stock_code"])] = payload

    def get_cluster_articles(self, cluster_id):
        article_ids = [
            article_id
            for (article_id, _stock), row in self.assignments.items()
            if row["cluster_id"] == cluster_id and row["status"] != "pending_retry"
        ]
        return [self.articles[article_id] for article_id in article_ids]

    def save_summary(self, cluster_id, parsed, meta, retry_count):
        self.summaries[cluster_id] = {
            "parsed": parsed,
            "meta": meta,
            "retry_count": retry_count,
        }


def article(article_id: int, title: str, published_at: str) -> dict[str, Any]:
    return {
        "article_id": article_id,
        "title": title,
        "description": "사건 설명",
        "body": "기사 본문",
        "press": "테스트뉴스",
        "published_at": published_at,
        "stock_codes": ["042660"],
        "retry_count": 0,
    }


def summary_ok(_prompt: str):
    return (
        {
            "title": "통합 제목",
            "easy_explanation": "초보자도 이해하기 쉬운 설명이에요.",
            "factual_body": "통합 본문입니다.",
        },
        {"ok": True, "parse_success": True},
    )


def test_company_new_existing_summary_and_article_id_idempotency() -> None:
    rows = [
        article(1, "한화오션, 함정 건조 계약 체결", "2026-07-20T01:00:00+00:00"),
        article(2, "한화오션 함정 건조 계약", "2026-07-20T02:00:00+00:00"),
    ]
    repo = MemoryClusterRepository(rows)
    cfg = Settings(use_llm_assign=True, upstage_api_key="test")
    service = NewsClusteringService(
        repo,
        cfg,
        embedder=FakeEmbedder({1: [1.0, 0.0], 2: [1.0, 0.0]}),
        assign_call_fn=lambda _prompt: (
            {"decision": "existing", "matched_cluster_id": 1},
            {"ok": True, "parse_success": True},
        ),
        summary_call_fn=summary_ok,
    )

    first = service.process_pending()
    second = service.process_pending()

    assert first["completed"] == 2
    assert len(repo.clusters) == 1
    assert repo.clusters[1]["article_count"] == 2
    assert repo.assignments[(1, "042660")]["status"] == "assigned_new"
    assert repo.assignments[(2, "042660")]["status"] == "assigned_existing"
    assert repo.summaries[1]["parsed"]["factual_body"] == "통합 본문입니다."
    assert second["scanned"] == 0


def test_llm_error_is_persisted_and_reprocessed_without_creating_cluster() -> None:
    base = article(10, "한화오션 수주 계약 체결", "2026-07-20T01:00:00+00:00")
    retry = article(11, "한화오션 수주 계약", "2026-07-20T02:00:00+00:00")
    repo = MemoryClusterRepository([retry])
    repo.create_cluster(article=base, stock_code="042660", kind="company", centroid=[1.0, 0.0])
    responses = iter(
        [
            ({}, {"ok": False, "parse_success": False, "raw": "timeout"}),
            (
                {"decision": "existing", "matched_cluster_id": 1},
                {"ok": True, "parse_success": True},
            ),
        ]
    )
    service = NewsClusteringService(
        repo,
        Settings(use_llm_assign=True, upstage_api_key="test"),
        embedder=FakeEmbedder({11: [1.0, 0.0]}),
        assign_call_fn=lambda _prompt: next(responses),
        summary_call_fn=summary_ok,
    )

    failed = service.process_pending()
    assert repo.assignments[(11, "042660")]["status"] == "pending_retry"
    assert repo.assignments[(11, "042660")]["cluster_id"] is None
    assert len(repo.clusters) == 1
    recovered = service.process_pending()

    assert failed["pending_retry"] == 1
    assert repo.assignments[(11, "042660")]["status"] == "assigned_existing"
    assert recovered["completed"] == 1
    assert len(repo.clusters) == 1
    assert repo.clusters[1]["article_count"] == 2


def test_market_keeps_same_day_rule_path_without_calling_assign_llm() -> None:
    row = article(20, "코스피 외국인 순매수에 상승", "2026-07-20T03:00:00+00:00")
    repo = MemoryClusterRepository([row])

    def unexpected_call(_prompt: str):
        raise AssertionError("market article must not call LLMAssigner")

    service = NewsClusteringService(
        repo,
        Settings(use_llm_assign=True, upstage_api_key="test"),
        embedder=FakeEmbedder({20: [0.0, 1.0]}),
        assign_call_fn=unexpected_call,
        summary_call_fn=summary_ok,
    )

    result = service.process_pending()

    assert result["completed"] == 1
    assert repo.processing[20]["kind"] == "market"
    assert repo.assignments[(20, "042660")]["llm_called"] is False
