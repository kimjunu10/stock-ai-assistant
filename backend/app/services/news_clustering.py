"""Incremental production pipeline for clustering crawled relevant news."""

from __future__ import annotations

import logging
import threading
from collections import OrderedDict
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
_EMBEDDING_CACHE_MAX_ITEMS = 4096
_embedding_cache: OrderedDict[str, np.ndarray] = OrderedDict()
_embedding_cache_lock = threading.Lock()

STOCK_NAMES = {
    "005930": "삼성전자",
    "000660": "SK하이닉스",
    "034020": "두산에너빌리티",
    "042660": "한화오션",
    "005380": "현대차",
}


class Embedder(Protocol):
    def encode(self, article: dict[str, Any]) -> np.ndarray: ...


class BackfillBudgetExhausted(RuntimeError):
    """Raised before a Solar call when a configured safety limit is reached."""


@lru_cache(maxsize=4)
def _load_embedding_model(model_name: str, revision: str, device: str):
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(model_name, revision=revision, device=device)


class BgeM3Embedder:
    """Lazy, process-cached BGE-M3 encoder using the experiment's exact input format."""

    def __init__(self, device: str):
        self.device = device
        self._encode_lock = threading.Lock()

    def encode(self, article: dict[str, Any]) -> np.ndarray:
        return self.encode_many([article])[0]

    def encode_many(self, articles: list[dict[str, Any]], *, batch_size: int = 32) -> np.ndarray:
        """Batch encoding used by read-only backfill planning."""

        if not articles:
            return np.empty((0, cluster_cfg.EMBEDDING_DIM), dtype=np.float32)
        texts: list[str] = []
        for article in articles:
            title = (article.get("title") or "").strip()
            description = (article.get("description") or "").strip()
            texts.append(" ".join(part for part in (title, description) if part))

        cache_keys = [
            "\x1f".join(
                (
                    cluster_cfg.EMBEDDING_MODEL,
                    cluster_cfg.EMBEDDING_REVISION,
                    self.device,
                    text,
                )
            )
            for text in texts
        ]
        vectors: list[np.ndarray | None] = [None] * len(texts)
        missing: dict[str, str] = {}
        with _embedding_cache_lock:
            for index, (key, text) in enumerate(zip(cache_keys, texts, strict=True)):
                cached = _embedding_cache.get(key)
                if cached is None:
                    missing.setdefault(key, text)
                    continue
                _embedding_cache.move_to_end(key)
                vectors[index] = cached

        if missing:
            missing_keys = list(missing)
            missing_texts = [missing[key] for key in missing_keys]
            with self._encode_lock:
                model = _load_embedding_model(
                    cluster_cfg.EMBEDDING_MODEL,
                    cluster_cfg.EMBEDDING_REVISION,
                    self.device,
                )
                encoded = model.encode(
                    missing_texts,
                    batch_size=batch_size,
                    convert_to_numpy=True,
                    normalize_embeddings=True,
                    show_progress_bar=False,
                )
            encoded = np.asarray(encoded, dtype=np.float32)
            with _embedding_cache_lock:
                for key, vector in zip(missing_keys, encoded, strict=True):
                    _embedding_cache[key] = vector
                    _embedding_cache.move_to_end(key)
                while len(_embedding_cache) > _EMBEDDING_CACHE_MAX_ITEMS:
                    _embedding_cache.popitem(last=False)

        with _embedding_cache_lock:
            for index, key in enumerate(cache_keys):
                if vectors[index] is None:
                    vectors[index] = _embedding_cache[key]
        return np.stack([np.asarray(vector, dtype=np.float32) for vector in vectors])


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
        progress_fn: Callable[[dict[str, Any], str, dict[str, int]], None] | None = None,
        defer_summaries: bool = False,
        dirty_run_key: str | None = None,
        manage_article_state: bool = True,
    ) -> None:
        self.repo = repo
        self.cfg = cfg
        self.embedder = embedder or BgeM3Embedder(cfg.news_embedding_device)
        self.assign_call_fn = assign_call_fn
        self.summary_call_fn = summary_call_fn or (
            lambda prompt: summarize.call_solar(cfg.upstage_api_key, prompt)
        )
        self.progress_fn = progress_fn
        self.defer_summaries = defer_summaries
        self.dirty_run_key = dirty_run_key
        self.manage_article_state = manage_article_state
        self._metrics: dict[str, int] = {}

    def process_pending(
        self,
        limit: int | None = None,
        *,
        candidates: list[dict[str, Any]] | None = None,
        retry_summaries: bool = True,
    ) -> dict[str, int]:
        limit = limit or self.cfg.news_clustering_batch_size
        totals = {
            "scanned": 0,
            "pairs_scanned": 0,
            "completed": 0,
            "pending_retry": 0,
            "duplicate": 0,
            "summaries_retried": 0,
            "assigned_new": 0,
            "assigned_existing": 0,
            "assignment_calls": 0,
            "summary_calls": 0,
            "stopped_budget": 0,
        }
        self._metrics = totals
        summary_retries = self.repo.get_summary_retry_clusters(limit) if retry_summaries else []
        for cluster in summary_retries:
            try:
                self._summarize_cluster(
                    int(cluster["id"]),
                    cluster["stock_code"],
                    int(cluster.get("summary_retry_count") or 0) + 1,
                )
                totals["summaries_retried"] += 1
            except BackfillBudgetExhausted:
                totals["stopped_budget"] = 1
                return totals
            except Exception:  # noqa: BLE001 - isolate one summary retry
                logger.exception("NEWS_SUMMARY_RETRY_FAILED cluster_id=%s", cluster.get("id"))

        articles = (
            candidates if candidates is not None else self.repo.get_pipeline_candidates(limit)
        )
        for article in articles:
            totals["scanned"] += 1
            totals["pairs_scanned"] += int(article.get("pair_count") or len(article["stock_codes"]))
            try:
                outcome = self._process_article(article)
            except BackfillBudgetExhausted:
                if self.manage_article_state:
                    self.repo.clear_article_processing(int(article["article_id"]))
                totals["stopped_budget"] = 1
                break
            totals[outcome] += 1
            if self.progress_fn is not None:
                self.progress_fn(article, outcome, totals)
        return totals

    def _process_article(self, article: dict[str, Any]) -> str:
        article_id = int(article["article_id"])
        kind = market_rules.classify_kind(article.get("title", ""), article.get("description", ""))
        retry_count = int(article.get("retry_count") or 0) + 1
        if self.manage_article_state:
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
        except BackfillBudgetExhausted:
            raise
        except Exception as exc:  # noqa: BLE001 - persist and isolate one article
            logger.exception("NEWS_CLUSTER_PROCESS_FAILED article_id=%d", article_id)
            errors.append(f"{type(exc).__name__}: {exc}")

        if errors:
            if self.manage_article_state:
                self.repo.mark_article_retry(article_id, kind, retry_count, "; ".join(errors))
            else:
                for stock_code in article["stock_codes"]:
                    previous = self.repo.get_assignment(article_id, stock_code)
                    if previous and previous["status"] in {"assigned_new", "assigned_existing"}:
                        continue
                    self.repo.save_assignment(
                        article_id=article_id,
                        stock_code=stock_code,
                        cluster_id=None,
                        kind=kind,
                        status="pending_retry",
                        llm_called=bool((previous or {}).get("llm_called")),
                        candidate_count=int((previous or {}).get("candidate_count") or 0),
                        reason="; ".join(errors),
                        error_code="unexpected_error",
                        retry_count=retry_count,
                    )
            return "pending_retry"
        if self.manage_article_state:
            if self.repo.has_unassigned_relevant_links(article_id):
                self.repo.clear_article_processing(article_id)
            else:
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
        if result.llm_called:
            self._metrics["assignment_calls"] += 1
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
                representative_article_id=int(article["article_id"]),
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
        self._record_cluster_change(cluster_id, stock_code, result.status)
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
                representative_article_id=int(article["article_id"]),
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
        self._record_cluster_change(cluster_id, stock_code, status)

    def _record_cluster_change(self, cluster_id: int, stock_code: str, status: str) -> None:
        self._metrics[status] += 1
        if self.defer_summaries:
            if not self.dirty_run_key:
                raise RuntimeError("dirty_run_key is required when summaries are deferred")
            self.repo.mark_cluster_dirty(self.dirty_run_key, cluster_id)
            return
        self._summarize_cluster(cluster_id, stock_code, 1)

    def _summarize_cluster(self, cluster_id: int, stock_code: str, retry_count: int) -> None:
        articles = self.repo.get_cluster_articles(cluster_id)
        prompt = summarize.build_user_prompt(
            articles[: cluster_cfg.MAX_ARTICLES_PER_SUMMARY],
            STOCK_NAMES.get(stock_code, stock_code),
        )
        try:
            parsed, meta = self.summary_call_fn(prompt)
        except BackfillBudgetExhausted:
            raise
        except Exception as exc:  # noqa: BLE001 - summary has its own persistent retry state
            parsed, meta = {}, {"ok": False, "parse_success": False, "raw": str(exc)}
        else:
            self._metrics["summary_calls"] += 1
        self.repo.save_summary(cluster_id, parsed, meta, retry_count)
