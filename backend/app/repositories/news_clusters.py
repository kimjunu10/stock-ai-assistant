"""Supabase persistence boundary for the incremental news-clustering pipeline."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from supabase import Client

from app.core.config import Settings


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

    def get_pipeline_candidates(self, limit: int) -> list[dict[str, Any]]:
        """Return crawled relevant articles not completed, including due retries."""

        now = _now()
        stale = now - timedelta(minutes=30)
        selected: list[dict[str, Any]] = []
        offset = 0
        page_size = max(100, limit * 4)
        while len(selected) < limit:
            response = (
                self.client.table("article_stocks")
                .select(
                    "article_id,stock_code,articles!inner("
                    "id,title,description,body,press,published_at,crawl_status)"
                )
                .eq("relevance", "relevant")
                .eq("articles.crawl_status", "success")
                .order("article_id")
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
                .select("article_id,stock_code,status")
                .in_("article_id", article_ids)
                .in_("status", ["assigned_new", "assigned_existing"])
                .execute()
            )
            completed_links = {
                (int(row["article_id"]), row["stock_code"])
                for row in assignments_response.data or []
            }
            grouped: dict[int, dict[str, Any]] = {}
            for link in links:
                article_id = int(link["article_id"])
                state = states.get(article_id)
                if state:
                    status = state["status"]
                    if (
                        status == "completed"
                        and (
                            article_id,
                            link["stock_code"],
                        )
                        in completed_links
                    ):
                        continue
                    retry_at = _parse(state.get("next_retry_at")) or now
                    if status == "pending_retry" and retry_at > now:
                        continue
                    if status == "processing" and (_parse(state.get("updated_at")) or now) > stale:
                        continue
                row = grouped.setdefault(
                    article_id,
                    {
                        **(link.get("articles") or {}),
                        "article_id": article_id,
                        "stock_codes": [],
                        "retry_count": int((state or {}).get("retry_count") or 0),
                    },
                )
                if link["stock_code"] not in row["stock_codes"]:
                    row["stock_codes"].append(link["stock_code"])
            for row in grouped.values():
                if any(item["article_id"] == row["article_id"] for item in selected):
                    continue
                selected.append(row)
                if len(selected) >= limit:
                    break
            if len(links) < page_size:
                break
            offset += page_size

        # A page can end between two stock links for one article. Re-read all links for
        # selected article_ids so completing the article never drops a later stock link.
        selected_ids = [int(row["article_id"]) for row in selected]
        if selected_ids:
            all_links_response = (
                self.client.table("article_stocks")
                .select("article_id,stock_code")
                .eq("relevance", "relevant")
                .in_("article_id", selected_ids)
                .execute()
            )
            stocks_by_article: dict[int, list[str]] = {}
            for link in all_links_response.data or []:
                stocks_by_article.setdefault(int(link["article_id"]), []).append(link["stock_code"])
            for row in selected:
                row["stock_codes"] = sorted(
                    set(stocks_by_article.get(int(row["article_id"]), row["stock_codes"]))
                )
        return selected

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
        cutoff = (published - timedelta(hours=window_hours)).isoformat()
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
        return int(rows[0]["id"])

    def update_cluster(
        self, cluster_id: int, *, centroid: list[float], article_count: int, last_active_at: str
    ) -> None:
        self.client.table("news_clusters").update(
            {
                "centroid": centroid,
                "article_count": article_count,
                "last_active_at": last_active_at,
                "summary_status": "pending",
                "summary_error": None,
                "summary_next_retry_at": None,
            }
        ).eq("id", cluster_id).execute()

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
                "summary_prompt_version": "factual_easy_v2",
                "summary_error": None,
                "summary_retry_count": retry_count,
                "summary_next_retry_at": None,
                "summarized_at": _now().isoformat(),
            }
        else:
            payload = {
                "summary_status": "pending_retry",
                "summary_prompt_version": "factual_easy_v2",
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
