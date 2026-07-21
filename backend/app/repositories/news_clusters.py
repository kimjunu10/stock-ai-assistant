"""Supabase persistence boundary for the incremental news-clustering pipeline."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from supabase import Client

from app.core.config import Settings
from experiments.exp_b_factual_summaries import config as cluster_cfg


def _now() -> datetime:
    return datetime.now(UTC)


def _parse(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


class NewsClusterRepository:
    """Persist idempotency, assignments, cluster state, and retry queues."""

    def __init__(self, client: Client, cfg: Settings):
        self.client = client
        self.cfg = cfg
        self._cluster_cache: dict[int, dict[str, Any]] | None = None

    def enable_cluster_cache(self, stock_code: str, page_size: int = 100) -> None:
        """Load one worker's stock clusters once to avoid repeated centroid transfers."""

        cache: dict[int, dict[str, Any]] = {}
        offset = 0
        while True:
            response = (
                self.client.table("news_clusters")
                .select(
                    "id,stock_code,kind,centroid,article_count,last_active_at,"
                    "anchor_article_id,anchor:articles!news_clusters_anchor_article_id_fkey("
                    "title,description)"
                )
                .eq("stock_code", stock_code)
                .order("id")
                .range(offset, offset + page_size - 1)
                .execute()
            )
            rows = list(response.data or [])
            for row in rows:
                cache[int(row["id"])] = row
            if len(rows) < page_size:
                break
            offset += page_size
        self._cluster_cache = cache

    def get_pipeline_candidates(self, limit: int) -> list[dict[str, Any]]:
        """Return up to ``limit`` unassigned pairs in publication order.

        ``limit`` is deliberately counted in ``(article_id, stock_code)`` units rather
        than articles. Successful assignments are the source of truth for resume.
        """

        now = _now()
        stale = now - timedelta(minutes=30)
        selected_pairs: list[dict[str, Any]] = []
        offset = 0
        page_size = 1000
        while len(selected_pairs) < limit:
            response = (
                self.client.table("article_stocks")
                .select(
                    "article_id,stock_code,articles!inner("
                    "id,title,description,body,press,published_at,crawl_status)"
                )
                .eq("relevance", "relevant")
                .eq("articles.crawl_status", "success")
                .order("published_at", foreign_table="articles")
                .order("article_id")
                .order("stock_code")
                .range(offset, offset + page_size - 1)
                .execute()
            )
            links = response.data or []
            if not links:
                break
            article_ids = sorted({int(row["article_id"]) for row in links})
            states_response = (
                self.client.table("news_article_processing")
                .select("article_id,status,retry_count,next_retry_at,updated_at")
                .in_("article_id", article_ids)
                .execute()
            )
            states = {int(row["article_id"]): row for row in states_response.data or []}
            assignments_response = (
                self.client.table("news_cluster_assignments")
                .select("article_id,stock_code,status,next_retry_at")
                .in_("article_id", article_ids)
                .execute()
            )
            assignment_states = {
                (int(row["article_id"]), row["stock_code"]): row
                for row in assignments_response.data or []
            }
            for link in links:
                article_id = int(link["article_id"])
                pair = (article_id, link["stock_code"])
                assignment = assignment_states.get(pair)
                if assignment:
                    if assignment["status"] in {"assigned_new", "assigned_existing"}:
                        continue
                    if (
                        assignment["status"] == "pending_retry"
                        and (_parse(assignment.get("next_retry_at")) or now) > now
                    ):
                        continue
                state = states.get(article_id)
                if state:
                    status = state["status"]
                    retry_at = _parse(state.get("next_retry_at")) or now
                    if status == "pending_retry" and retry_at > now:
                        continue
                    if status == "processing" and (_parse(state.get("updated_at")) or now) > stale:
                        continue
                selected_pairs.append(
                    {
                        **(link.get("articles") or {}),
                        "article_id": article_id,
                        "stock_code": link["stock_code"],
                        "retry_count": int((state or {}).get("retry_count") or 0),
                    }
                )
                if len(selected_pairs) >= limit:
                    break
            if len(links) < page_size:
                break
            offset += page_size

        grouped: dict[int, dict[str, Any]] = {}
        for pair in selected_pairs:
            article_id = int(pair["article_id"])
            row = grouped.setdefault(
                article_id,
                {
                    **pair,
                    "stock_codes": [],
                    "pair_count": 0,
                },
            )
            row["stock_codes"].append(pair["stock_code"])
            row["pair_count"] += 1
        return list(grouped.values())

    def clear_article_processing(self, article_id: int) -> None:
        """Release a partially processed article so remaining pairs are immediately resumable."""

        self.client.table("news_article_processing").delete().eq("article_id", article_id).execute()

    def has_unassigned_relevant_links(self, article_id: int) -> bool:
        links = (
            self.client.table("article_stocks")
            .select("stock_code")
            .eq("article_id", article_id)
            .eq("relevance", "relevant")
            .execute()
        ).data or []
        assigned = (
            self.client.table("news_cluster_assignments")
            .select("stock_code")
            .eq("article_id", article_id)
            .in_("status", ["assigned_new", "assigned_existing"])
            .execute()
        ).data or []
        return bool({row["stock_code"] for row in links} - {row["stock_code"] for row in assigned})

    def mark_article_processing(self, article_id: int, kind: str, retry_count: int) -> None:
        self.client.table("news_article_processing").upsert(
            {
                "article_id": article_id,
                "kind": kind,
                "status": "processing",
                "retry_count": retry_count,
                "next_retry_at": None,
                "last_error": None,
                "started_at": _now().isoformat(),
                "completed_at": None,
            },
            on_conflict="article_id",
        ).execute()

    def mark_article_complete(self, article_id: int, kind: str) -> None:
        now = _now().isoformat()
        self.client.table("news_article_processing").update(
            {
                "kind": kind,
                "status": "completed",
                "next_retry_at": None,
                "last_error": None,
                "completed_at": now,
            }
        ).eq("article_id", article_id).execute()

    def mark_article_retry(self, article_id: int, kind: str, retry_count: int, error: str) -> None:
        retry_at = _now() + timedelta(minutes=self.cfg.news_clustering_retry_minutes)
        self.client.table("news_article_processing").upsert(
            {
                "article_id": article_id,
                "kind": kind,
                "status": "pending_retry",
                "retry_count": retry_count,
                "next_retry_at": retry_at.isoformat(),
                "last_error": error[:1000],
                "completed_at": None,
            },
            on_conflict="article_id",
        ).execute()

    def get_assignment(self, article_id: int, stock_code: str) -> dict[str, Any] | None:
        response = (
            self.client.table("news_cluster_assignments")
            .select("*")
            .eq("article_id", article_id)
            .eq("stock_code", stock_code)
            .limit(1)
            .execute()
        )
        return (response.data or [None])[0]

    def get_active_clusters(
        self, stock_code: str, kind: str, published_at: str, window_hours: int = 72
    ) -> list[dict[str, Any]]:
        published = _parse(published_at)
        if published is None:
            return []
        cutoff_dt = published - timedelta(hours=window_hours)
        cutoff = cutoff_dt.isoformat()
        if self._cluster_cache is not None:
            return sorted(
                (
                    row
                    for row in self._cluster_cache.values()
                    if row["stock_code"] == stock_code
                    and row["kind"] == kind
                    and (_parse(row.get("last_active_at")) or published) >= cutoff_dt
                    and (_parse(row.get("last_active_at")) or published) <= published
                ),
                key=lambda row: row["last_active_at"],
                reverse=True,
            )
        response = (
            self.client.table("news_clusters")
            .select(
                "id,stock_code,kind,centroid,article_count,last_active_at,"
                "anchor_article_id,anchor:articles!news_clusters_anchor_article_id_fkey("
                "title,description)"
            )
            .eq("stock_code", stock_code)
            .eq("kind", kind)
            .gte("last_active_at", cutoff)
            .lte("last_active_at", published.isoformat())
            .order("last_active_at", desc=True)
            .execute()
        )
        return list(response.data or [])

    def create_cluster(
        self, *, article: dict[str, Any], stock_code: str, kind: str, centroid: list[float]
    ) -> int:
        response = (
            self.client.table("news_clusters")
            .insert(
                {
                    "stock_code": stock_code,
                    "kind": kind,
                    "anchor_article_id": article["article_id"],
                    "representative_article_id": article["article_id"],
                    "centroid": centroid,
                    "article_count": 1,
                    "first_published_at": article["published_at"],
                    "last_active_at": article["published_at"],
                    "clustering_version": "bge_m3_title_desc_centroid_bridge_info_v3",
                    "summary_status": "pending",
                }
            )
            .execute()
        )
        rows = response.data or []
        if not rows:
            raise RuntimeError("Supabase did not return the created news cluster")
        cluster_id = int(rows[0]["id"])
        if self._cluster_cache is not None:
            self._cluster_cache[cluster_id] = {
                **rows[0],
                "anchor": {
                    "title": article.get("title") or "",
                    "description": article.get("description") or "",
                },
            }
        return cluster_id

    def update_cluster(
        self,
        cluster_id: int,
        *,
        centroid: list[float],
        article_count: int,
        last_active_at: str,
        representative_article_id: int | None = None,
    ) -> None:
        payload: dict[str, Any] = {
            "centroid": centroid,
            "article_count": article_count,
            "last_active_at": last_active_at,
            "summary_status": "pending",
            "summary_error": None,
            "summary_next_retry_at": None,
        }
        if representative_article_id is not None:
            payload["representative_article_id"] = representative_article_id
        self.client.table("news_clusters").update(payload).eq("id", cluster_id).execute()
        if self._cluster_cache is not None and cluster_id in self._cluster_cache:
            self._cluster_cache[cluster_id].update(payload)

    def save_assignment(
        self,
        *,
        article_id: int,
        stock_code: str,
        cluster_id: int | None,
        kind: str,
        status: str,
        llm_called: bool,
        candidate_count: int,
        reason: str,
        error_code: str | None,
        retry_count: int,
    ) -> None:
        retry_at = None
        assigned_at = _now().isoformat() if cluster_id is not None else None
        if status == "pending_retry":
            retry_at = (
                _now() + timedelta(minutes=self.cfg.news_clustering_retry_minutes)
            ).isoformat()
        self.client.table("news_cluster_assignments").upsert(
            {
                "article_id": article_id,
                "stock_code": stock_code,
                "cluster_id": cluster_id,
                "kind": kind,
                "status": status,
                "llm_called": llm_called,
                "candidate_count": candidate_count,
                "assignment_reason": reason,
                "error_code": error_code,
                "prompt_version": "same_event_v1" if llm_called else None,
                "retry_count": retry_count,
                "next_retry_at": retry_at,
                "assigned_at": assigned_at,
            },
            on_conflict="article_id,stock_code",
        ).execute()

    def get_cluster_articles(self, cluster_id: int) -> list[dict[str, Any]]:
        response = (
            self.client.table("news_cluster_assignments")
            .select("articles!inner(id,title,description,body,press,published_at)")
            .eq("cluster_id", cluster_id)
            .in_("status", ["assigned_new", "assigned_existing"])
            .order("assigned_at")
            .execute()
        )
        return [row["articles"] for row in response.data or [] if row.get("articles")]

    def save_summary(
        self, cluster_id: int, parsed: dict[str, Any], meta: dict[str, Any], retry_count: int
    ) -> None:
        if meta.get("ok") and meta.get("parse_success"):
            payload = {
                "summary_title": parsed["title"],
                "easy_explanation": parsed["easy_explanation"],
                "factual_body": parsed["factual_body"],
                "summary_status": "success",
                "summary_prompt_version": cluster_cfg.SUMMARY_PROMPT_VERSION,
                "summary_error": None,
                "summary_retry_count": retry_count,
                "summary_next_retry_at": None,
                "summarized_at": _now().isoformat(),
            }
        else:
            payload = {
                "summary_status": "pending_retry",
                "summary_prompt_version": cluster_cfg.SUMMARY_PROMPT_VERSION,
                "summary_error": str(meta.get("raw") or "invalid summary response")[:1000],
                "summary_retry_count": retry_count,
                "summary_next_retry_at": (
                    _now() + timedelta(minutes=self.cfg.news_clustering_retry_minutes)
                ).isoformat(),
            }
        self.client.table("news_clusters").update(payload).eq("id", cluster_id).execute()

    def get_summary_retry_clusters(self, limit: int) -> list[dict[str, Any]]:
        response = (
            self.client.table("news_clusters")
            .select("id,stock_code,summary_status,summary_retry_count,summary_next_retry_at")
            .in_("summary_status", ["pending", "pending_retry"])
            .order("updated_at")
            .limit(limit * 4)
            .execute()
        )
        now = _now()
        return [
            row
            for row in response.data or []
            if row["summary_status"] == "pending"
            or (_parse(row.get("summary_next_retry_at")) or now) <= now
        ][:limit]

    def start_backfill_run(self, run_key: str, limits: dict[str, Any]) -> None:
        self.client.table("news_backfill_runs").upsert(
            {
                "run_key": run_key,
                "status": "running",
                "started_at": _now().isoformat(),
                "finished_at": None,
                "limits": limits,
                "last_error": None,
            },
            on_conflict="run_key",
        ).execute()

    def get_backfill_run(self, run_key: str) -> dict[str, Any] | None:
        response = (
            self.client.table("news_backfill_runs")
            .select("*")
            .eq("run_key", run_key)
            .limit(1)
            .execute()
        )
        return (response.data or [None])[0]

    def update_backfill_run(
        self,
        run_key: str,
        *,
        status: str,
        totals: dict[str, Any],
        usage: dict[str, Any],
        article: dict[str, Any] | None = None,
        last_error: str | None = None,
    ) -> None:
        payload: dict[str, Any] = {
            "status": status,
            "processed_articles": int(totals.get("scanned") or 0),
            "processed_pairs": int(totals.get("pairs_scanned") or 0),
            "completed_articles": int(totals.get("completed") or 0),
            "pending_retry_articles": int(totals.get("pending_retry") or 0),
            "assignment_calls": int(usage.get("assignment_calls") or 0),
            "summary_calls": int(usage.get("summary_calls") or 0),
            "prompt_tokens": int(usage.get("prompt_tokens") or 0),
            "completion_tokens": int(usage.get("completion_tokens") or 0),
            "estimated_cost_usd": float(usage.get("cost_usd") or 0),
            "totals": totals,
            "last_error": last_error,
        }
        if article is not None:
            payload.update(
                {
                    "last_success_article_id": int(article["article_id"]),
                    "last_success_stock_code": (article.get("stock_codes") or [None])[-1],
                    "last_success_published_at": article.get("published_at"),
                }
            )
        if status in {"stopped_budget", "stopped", "completed", "failed"}:
            payload["finished_at"] = _now().isoformat()
        self.client.table("news_backfill_runs").update(payload).eq("run_key", run_key).execute()

    def get_today_backfill_cost(self) -> float:
        seoul = ZoneInfo("Asia/Seoul")
        start = (
            _now()
            .astimezone(seoul)
            .replace(hour=0, minute=0, second=0, microsecond=0)
            .astimezone(UTC)
            .isoformat()
        )
        response = (
            self.client.table("news_backfill_runs")
            .select("estimated_cost_usd")
            .gte("started_at", start)
            .execute()
        )
        return sum(float(row.get("estimated_cost_usd") or 0) for row in response.data or [])

    def mark_cluster_dirty(self, run_key: str, cluster_id: int) -> None:
        self.client.table("news_backfill_dirty_clusters").upsert(
            {
                "run_key": run_key,
                "cluster_id": cluster_id,
                "status": "dirty",
                "next_retry_at": None,
                "last_error": None,
                "summarized_at": None,
            },
            on_conflict="run_key,cluster_id",
        ).execute()

    def get_dirty_clusters(self, run_key: str) -> list[dict[str, Any]]:
        fetched: list[dict[str, Any]] = []
        offset = 0
        page_size = 1000
        while True:
            response = (
                self.client.table("news_backfill_dirty_clusters")
                .select("run_key,cluster_id,status,retry_count,claimed_at,next_retry_at,last_error")
                .eq("run_key", run_key)
                .in_("status", ["dirty", "pending_retry", "processing"])
                .order("cluster_id")
                .range(offset, offset + page_size - 1)
                .execute()
            )
            page = list(response.data or [])
            fetched.extend(page)
            if len(page) < page_size:
                break
            offset += page_size
        now = _now()
        stale = now - timedelta(minutes=30)
        rows = []
        for row in fetched:
            if row["status"] == "pending_retry" and (_parse(row.get("next_retry_at")) or now) > now:
                continue
            if row["status"] == "processing" and (_parse(row.get("claimed_at")) or now) > stale:
                continue
            rows.append(row)
        return rows

    def mark_dirty_processing(self, run_key: str, cluster_id: int) -> None:
        self.client.table("news_backfill_dirty_clusters").update(
            {"status": "processing", "claimed_at": _now().isoformat()}
        ).eq("run_key", run_key).eq("cluster_id", cluster_id).neq("status", "success").execute()

    def mark_dirty_success(self, run_key: str, cluster_id: int) -> None:
        self.client.table("news_backfill_dirty_clusters").update(
            {
                "status": "success",
                "last_error": None,
                "next_retry_at": None,
                "summarized_at": _now().isoformat(),
            }
        ).eq("run_key", run_key).eq("cluster_id", cluster_id).execute()

    def mark_dirty_retry(self, run_key: str, cluster_id: int, retry_count: int, error: str) -> None:
        self.client.table("news_backfill_dirty_clusters").update(
            {
                "status": "pending_retry",
                "retry_count": retry_count,
                "last_error": error[:1000],
                "next_retry_at": (
                    _now() + timedelta(minutes=self.cfg.news_clustering_retry_minutes)
                ).isoformat(),
            }
        ).eq("run_key", run_key).eq("cluster_id", cluster_id).execute()

    def has_active_backfill(self) -> bool:
        cutoff = (_now() - timedelta(minutes=10)).isoformat()
        response = (
            self.client.table("news_backfill_runs")
            .select("run_key")
            .eq("status", "running")
            .gte("updated_at", cutoff)
            .limit(1)
            .execute()
        )
        return bool(response.data)

    def heartbeat_backfill(self, run_key: str, phase: str) -> None:
        self.client.table("news_backfill_runs").update(
            {"status": "running", "totals": {"phase": phase}}
        ).eq("run_key", run_key).execute()

    def claim_backfill_pair(self, run_key: str, article_id: int, stock_code: str) -> bool:
        response = self.client.rpc(
            "claim_news_backfill_pair",
            {
                "p_run_key": run_key,
                "p_article_id": article_id,
                "p_stock_code": stock_code,
            },
        ).execute()
        return bool(response.data)

    def finish_backfill_pair(
        self,
        run_key: str,
        article_id: int,
        stock_code: str,
        *,
        status: str,
        error: str | None = None,
    ) -> None:
        self.client.table("news_backfill_pair_claims").update(
            {
                "status": status,
                "finished_at": _now().isoformat(),
                "last_error": (error or "")[:1000] or None,
            }
        ).eq("run_key", run_key).eq("article_id", article_id).eq("stock_code", stock_code).execute()

    def release_backfill_claims(self, run_key: str, reason: str) -> None:
        self.client.table("news_backfill_pair_claims").update(
            {
                "status": "pending_retry",
                "finished_at": _now().isoformat(),
                "last_error": reason[:1000],
            }
        ).eq("run_key", run_key).eq("status", "processing").execute()

    def repair_backfill_dirty_clusters(self, run_key: str) -> int:
        response = self.client.rpc(
            "repair_news_backfill_dirty_clusters", {"p_run_key": run_key}
        ).execute()
        return int(response.data or 0)
