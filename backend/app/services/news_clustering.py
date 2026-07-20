"""Incremental production pipeline for clustering crawled relevant news."""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime
from functools import lru_cache
from typing import Any, Protocol

import numpy as np

from app.core.config import Settings
from experiments.exp_b_factual_summaries import config as cluster_cfg
from experiments.exp_b_factual_summaries import market_rules, summarize
from experiments.exp_b_factual_summaries.assign_llm import Cluster, LLMAssigner

logger = logging.getLogger(__name__)

STOCK_NAMES = {
    "005930": "삼성전자",
    "000660": "SK하이닉스",
    "034020": "두산에너빌리티",
    "042660": "한화오션",
    "005380": "현대차",
}


class Embedder(Protocol):
    def encode(self, article: dict[str, Any]) -> np.ndarray: ...


@lru_cache(maxsize=4)
def _load_embedding_model(model_name: str, revision: str, device: str):
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(model_name, revision=revision, device=device)


class BgeM3Embedder:
    """Lazy, process-cached BGE-M3 encoder using the experiment's exact input format."""

    def __init__(self, device: str):
        self.device = device

    def encode(self, article: dict[str, Any]) -> np.ndarray:
        title = (article.get("title") or "").strip()
        description = (article.get("description") or "").strip()
        text = " ".join(part for part in (title, description) if part)
        model = _load_embedding_model(
            cluster_cfg.EMBEDDING_MODEL,
            cluster_cfg.EMBEDDING_REVISION,
            self.device,
        )
        vector = model.encode(
            [text],
            convert_to_numpy=True,
            normalize_embeddings=True,
            show_progress_bar=False,
        )[0]
        return np.asarray(vector, dtype=np.float32)


def _hours(value: str) -> float:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.timestamp() / 3600.0


class NewsClusteringService:
    """Route by classify_kind, persist assignments, and refresh factual summaries."""

    def __init__(
        self,
        repo: Any,
        cfg: Settings,
        *,
        embedder: Embedder | None = None,
        assign_call_fn: Callable[[str], tuple[dict, dict]] | None = None,
        summary_call_fn: Callable[[str], tuple[dict, dict]] | None = None,
    ) -> None:
        self.repo = repo
        self.cfg = cfg
        self.embedder = embedder or BgeM3Embedder(cfg.news_embedding_device)
        self.assign_call_fn = assign_call_fn
        self.summary_call_fn = summary_call_fn or (
            lambda prompt: summarize.call_solar(cfg.upstage_api_key, prompt)
        )

    def process_pending(self, limit: int | None = None) -> dict[str, int]:
        limit = limit or self.cfg.news_clustering_batch_size
        totals = {
            "scanned": 0,
            "completed": 0,
            "pending_retry": 0,
            "duplicate": 0,
            "summaries_retried": 0,
        }
        for cluster in self.repo.get_summary_retry_clusters(limit):
            self._summarize_cluster(
                int(cluster["id"]),
                cluster["stock_code"],
                int(cluster.get("summary_retry_count") or 0) + 1,
            )
            totals["summaries_retried"] += 1

        for article in self.repo.get_pipeline_candidates(limit):
            totals["scanned"] += 1
            outcome = self._process_article(article)
            totals[outcome] += 1
        return totals

    def _process_article(self, article: dict[str, Any]) -> str:
        article_id = int(article["article_id"])
        kind = market_rules.classify_kind(article.get("title", ""), article.get("description", ""))
        retry_count = int(article.get("retry_count") or 0) + 1
        self.repo.mark_article_processing(article_id, kind, retry_count)
        vector: np.ndarray | None = None
        errors: list[str] = []
        processed_any = False

        try:
            for stock_code in article["stock_codes"]:
                previous = self.repo.get_assignment(article_id, stock_code)
                if previous and previous["status"] in {"assigned_new", "assigned_existing"}:
                    continue
                if vector is None:
                    vector = self.embedder.encode(article)
                processed_any = True
                if kind == "company":
                    error = self._assign_company(article, stock_code, vector, retry_count)
                else:
                    error = self._assign_rule_based(article, stock_code, kind, vector, retry_count)
                if error:
                    errors.append(f"{stock_code}: {error}")
        except Exception as exc:  # noqa: BLE001 - persist and isolate one article
            logger.exception("NEWS_CLUSTER_PROCESS_FAILED article_id=%d", article_id)
            errors.append(f"{type(exc).__name__}: {exc}")

        if errors:
            self.repo.mark_article_retry(article_id, kind, retry_count, "; ".join(errors))
            return "pending_retry"
        self.repo.mark_article_complete(article_id, kind)
        return "completed" if processed_any else "duplicate"

    def _hydrate_assigner(self, rows: list[dict[str, Any]]) -> LLMAssigner:
        assigner = LLMAssigner(
            api_key=self.cfg.upstage_api_key,
            call_fn=self.assign_call_fn,
            use_llm=self.cfg.use_llm_assign,
            window_hours=cluster_cfg.ACTIVE_WINDOW_HOURS,
            max_candidates=cluster_cfg.LLM_ASSIGN_MAX_CANDIDATES,
            candidate_min_sim=cluster_cfg.LLM_ASSIGN_CANDIDATE_MIN_SIM,
        )
        max_id = 0
        for row in rows:
            cluster_id = int(row["id"])
            anchor = row.get("anchor") or {}
            count = int(row.get("article_count") or 1)
            assigner.clusters[cluster_id] = Cluster(
                cluster_id=cluster_id,
                stock_code=row["stock_code"],
                centroid=np.asarray(row["centroid"], dtype=np.float32),
                anchor_title=anchor.get("title") or "",
                anchor_description=anchor.get("description") or "",
                rep_title=anchor.get("title") or "",
                rep_description=anchor.get("description") or "",
                member_article_ids=[f"persisted:{cluster_id}:{i}" for i in range(count)],
                last_active_h=_hours(row["last_active_at"]),
            )
            max_id = max(max_id, cluster_id)
        assigner._next_id = max_id + 1
        return assigner

    def _assign_company(
        self,
        article: dict[str, Any],
        stock_code: str,
        vector: np.ndarray,
        retry_count: int,
    ) -> str | None:
        active = self.repo.get_active_clusters(
            stock_code, "company", article["published_at"], cluster_cfg.ACTIVE_WINDOW_HOURS
        )
        assigner = self._hydrate_assigner(active)
        assign_article = {
            "article_id": str(article["article_id"]),
            "stock_code": stock_code,
            "title": article.get("title") or "",
            "description": article.get("description") or "",
        }
        result = assigner.assign(assign_article, vector, _hours(article["published_at"]))
        if result.status == "pending_retry":
            self.repo.save_assignment(
                article_id=int(article["article_id"]),
                stock_code=stock_code,
                cluster_id=None,
                kind="company",
                status="pending_retry",
                llm_called=result.llm_called,
                candidate_count=result.n_candidates,
                reason=result.reason,
                error_code=result.error,
                retry_count=retry_count,
            )
            return result.error or result.reason

        if result.status == "assigned_new":
            cluster_id = self.repo.create_cluster(
                article=article,
                stock_code=stock_code,
                kind="company",
                centroid=vector.astype(float).tolist(),
            )
        else:
            cluster_id = int(result.cluster_id)
            cluster = assigner.clusters[cluster_id]
            self.repo.update_cluster(
                cluster_id,
                centroid=cluster.centroid.astype(float).tolist(),
                article_count=len(cluster.member_article_ids),
                last_active_at=article["published_at"],
            )
        self.repo.save_assignment(
            article_id=int(article["article_id"]),
            stock_code=stock_code,
            cluster_id=cluster_id,
            kind="company",
            status=result.status,
            llm_called=result.llm_called,
            candidate_count=result.n_candidates,
            reason=result.reason,
            error_code=None,
            retry_count=retry_count,
        )
        self._summarize_cluster(cluster_id, stock_code, 1)
        return None

    def _assign_rule_based(
        self,
        article: dict[str, Any],
        stock_code: str,
        kind: str,
        vector: np.ndarray,
        retry_count: int,
    ) -> None:
        active = self.repo.get_active_clusters(
            stock_code, kind, article["published_at"], cluster_cfg.ACTIVE_WINDOW_HOURS
        )
        day = market_rules.market_day_bucket(article["published_at"])
        same_day = [
            row for row in active if market_rules.market_day_bucket(row["last_active_at"]) == day
        ]
        best_row, best_sim = None, cluster_cfg.COSINE_THRESHOLD
        for row in same_day:
            similarity = float(np.dot(vector, np.asarray(row["centroid"], dtype=np.float32)))
            if similarity >= best_sim:
                best_row, best_sim = row, similarity

        if best_row is None:
            cluster_id = self.repo.create_cluster(
                article=article,
                stock_code=stock_code,
                kind=kind,
                centroid=vector.astype(float).tolist(),
            )
            status, reason = "assigned_new", "rule: no same-day match"
        else:
            count = int(best_row.get("article_count") or 1)
            centroid = np.asarray(best_row["centroid"], dtype=np.float32)
            updated = (centroid * count + vector) / (count + 1)
            norm = np.linalg.norm(updated)
            if norm:
                updated /= norm
            cluster_id = int(best_row["id"])
            self.repo.update_cluster(
                cluster_id,
                centroid=updated.astype(float).tolist(),
                article_count=count + 1,
                last_active_at=article["published_at"],
            )
            status, reason = "assigned_existing", f"rule: cosine={best_sim:.6f}"
        self.repo.save_assignment(
            article_id=int(article["article_id"]),
            stock_code=stock_code,
            cluster_id=cluster_id,
            kind=kind,
            status=status,
            llm_called=False,
            candidate_count=1 if best_row else 0,
            reason=reason,
            error_code=None,
            retry_count=retry_count,
        )
        self._summarize_cluster(cluster_id, stock_code, 1)

    def _summarize_cluster(self, cluster_id: int, stock_code: str, retry_count: int) -> None:
        articles = self.repo.get_cluster_articles(cluster_id)
        prompt = summarize.build_user_prompt(
            articles[: cluster_cfg.MAX_ARTICLES_PER_SUMMARY],
            STOCK_NAMES.get(stock_code, stock_code),
        )
        try:
            parsed, meta = self.summary_call_fn(prompt)
        except Exception as exc:  # noqa: BLE001 - summary has its own persistent retry state
            parsed, meta = {}, {"ok": False, "parse_success": False, "raw": str(exc)}
        self.repo.save_summary(cluster_id, parsed, meta, retry_count)
