"""뉴스 처리 v2 전용 persistence. v1(news_clusters.py)을 건드리지 않는다.

- 역할 분류 결과를 article_stocks 의 role_* 컬럼에 저장(멱등 캐시).
- v2 클러스터는 clustering_version = V2_VERSION 으로 쌓아 v1 과 분리.
- v2 assignment 는 clustering_version 로 v1 assignment 와 구분해 조회한다.
  (news_cluster_assignments 는 (article_id, stock_code) PK 라 종목별 1행이므로,
   v2 배정은 cluster_id 가 v2 클러스터를 가리키는지로 구분한다.)
- 활성 버전 전환은 news_pipeline_state.active_version 을 바꾼다.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from supabase import Client

V2_VERSION = "v2_event_role_20260721"


def _now() -> datetime:
    return datetime.now(UTC)


def _parse(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


class NewsV2Repository:
    """v2 역할분류 · 클러스터링 · 요약 · 활성화 persistence."""

    def __init__(self, client: Client, cfg: Any, *, version: str = V2_VERSION):
        self.client = client
        self.cfg = cfg
        self.version = version

    # ----------------------------------------------------------------- 종목
    def get_stock_names(self) -> dict[str, str]:
        rows = (self.client.table("stocks").select("code,name").execute()).data or []
        return {r["code"]: r["name"] for r in rows}

    # ------------------------------------------------------------- 역할 분류
    def get_relevant_pairs_for_roles(self, *, only_unclassified: bool) -> list[dict[str, Any]]:
        """relevant + crawl_status=success pair 를 발행 시각순으로 반환.

        only_unclassified=True 면 아직 role_version 이 현재 버전이 아닌 pair 만.
        """
        out: list[dict[str, Any]] = []
        offset = 0
        page = 1000
        while True:
            resp = (
                self.client.table("article_stocks")
                .select(
                    "article_id,stock_code,article_role,role_version,"
                    "articles!inner(id,title,description,body,published_at,crawl_status)"
                )
                .eq("relevance", "relevant")
                .eq("articles.crawl_status", "success")
                .order("published_at", foreign_table="articles")
                .order("article_id")
                .order("stock_code")
                .range(offset, offset + page - 1)
                .execute()
            )
            rows = resp.data or []
            for r in rows:
                if only_unclassified and r.get("role_version") == self.version:
                    continue
                art = r.get("articles") or {}
                out.append(
                    {
                        "article_id": int(r["article_id"]),
                        "stock_code": r["stock_code"],
                        "title": art.get("title") or "",
                        "description": art.get("description") or "",
                        "body": art.get("body") or "",
                        "published_at": art.get("published_at") or "",
                    }
                )
            if len(rows) < page:
                break
            offset += page
        return out

    def save_role(self, article_id: int, stock_code: str, result: dict[str, Any]) -> None:
        """역할 분류 결과를 article_stocks 에 저장(멱등 캐시)."""
        self.client.table("article_stocks").update(
            {
                "article_role": result["article_role"],
                "event_eligible": bool(result["event_eligible"]),
                "role_reason": (result.get("reason") or "")[:1000],
                "role_source": result.get("role_source"),
                "role_version": self.version,
                "event_signature": result.get("event_signature"),
                "role_classified_at": _now().isoformat(),
            }
        ).eq("article_id", article_id).eq("stock_code", stock_code).execute()

    def count_roles(self) -> dict[str, int]:
        """현재 버전으로 분류된 pair 의 역할별 카운트."""
        counts: dict[str, int] = {}
        offset = 0
        page = 1000
        while True:
            resp = (
                self.client.table("article_stocks")
                .select("article_role")
                .eq("relevance", "relevant")
                .eq("role_version", self.version)
                .range(offset, offset + page - 1)
                .execute()
            )
            rows = resp.data or []
            for r in rows:
                counts[r["article_role"]] = counts.get(r["article_role"], 0) + 1
            if len(rows) < page:
                break
            offset += page
        return counts

    # ------------------------------------------------------- 클러스터링 대상
    def get_event_pairs(self) -> list[dict[str, Any]]:
        """company_event + event_eligible=true 인 pair 를 발행 시각순으로.

        v2 클러스터링 입력. event_signature 를 함께 싣는다.
        """
        out: list[dict[str, Any]] = []
        offset = 0
        page = 1000
        while True:
            resp = (
                self.client.table("article_stocks")
                .select(
                    "article_id,stock_code,event_signature,"
                    "articles!inner(id,title,description,published_at,crawl_status)"
                )
                .eq("relevance", "relevant")
                .eq("event_eligible", True)
                .eq("article_role", "company_event")
                .eq("role_version", self.version)
                .eq("articles.crawl_status", "success")
                .order("published_at", foreign_table="articles")
                .order("article_id")
                .order("stock_code")
                .range(offset, offset + page - 1)
                .execute()
            )
            rows = resp.data or []
            for r in rows:
                art = r.get("articles") or {}
                out.append(
                    {
                        "article_id": int(r["article_id"]),
                        "stock_code": r["stock_code"],
                        "title": art.get("title") or "",
                        "description": art.get("description") or "",
                        "published_at": art.get("published_at") or "",
                        "event_signature": r.get("event_signature"),
                    }
                )
            if len(rows) < page:
                break
            offset += page
        return out

    def get_assigned_v2_pairs(self) -> set[tuple[int, str]]:
        """이미 v2 클러스터에 성공 배정된 (article_id, stock_code) 집합(멱등 재개용, 배치).

        pair 마다 개별 조회하지 않고 한 번에 로드해 재실행 시 스킵 판정을 빠르게 한다.
        """
        out: set[tuple[int, str]] = set()
        offset = 0
        page = 1000
        while True:
            resp = (
                self.client.table("news_cluster_assignments")
                .select("article_id,stock_code,status,news_clusters!inner(clustering_version)")
                .eq("news_clusters.clustering_version", self.version)
                .in_("status", ["assigned_new", "assigned_existing"])
                .range(offset, offset + page - 1)
                .execute()
            )
            rows = resp.data or []
            for r in rows:
                out.add((int(r["article_id"]), r["stock_code"]))
            if len(rows) < page:
                break
            offset += page
        return out

    def get_v2_assignment_clusters(self, stock_code: str) -> list[dict[str, Any]]:
        """Return persisted v2 clusters needed to resume incremental assignment.

        The assigner must see clusters created by earlier runs. Otherwise the first
        article in every resumed batch has no candidates and is incorrectly forced
        into a new cluster.
        """

        out: list[dict[str, Any]] = []
        offset = 0
        page = 1000
        while True:
            resp = (
                self.client.table("news_clusters")
                .select(
                    "id,stock_code,centroid,article_count,last_active_at,event_signature,"
                    "anchor:articles!news_clusters_anchor_article_id_fkey(title,description),"
                    "representative:articles!news_clusters_representative_article_id_fkey("
                    "title,description)"
                )
                .eq("clustering_version", self.version)
                .eq("stock_code", stock_code)
                .order("id")
                .range(offset, offset + page - 1)
                .execute()
            )
            rows = resp.data or []
            out.extend(rows)
            if len(rows) < page:
                break
            offset += page
        return out

    def get_v2_assignment(self, article_id: int, stock_code: str) -> dict[str, Any] | None:
        """이 pair 가 이미 v2 클러스터에 배정됐는지(멱등 재개용)."""
        resp = (
            self.client.table("news_cluster_assignments")
            .select(
                "article_id,stock_code,cluster_id,status,news_clusters!inner(clustering_version)"
            )
            .eq("article_id", article_id)
            .eq("stock_code", stock_code)
            .eq("news_clusters.clustering_version", self.version)
            .limit(1)
            .execute()
        )
        return (resp.data or [None])[0]

    def create_v2_cluster(
        self,
        *,
        article: dict[str, Any],
        stock_code: str,
        centroid: list[float],
        event_signature: dict | None,
    ) -> int:
        resp = (
            self.client.table("news_clusters")
            .insert(
                {
                    "stock_code": stock_code,
                    "kind": "company",
                    "anchor_article_id": article["article_id"],
                    "representative_article_id": article["article_id"],
                    "centroid": centroid,
                    "article_count": 1,
                    "first_published_at": article["published_at"],
                    "last_active_at": article["published_at"],
                    "clustering_version": self.version,
                    "event_signature": event_signature,
                    "summary_status": "pending",
                }
            )
            .execute()
        )
        rows = resp.data or []
        if not rows:
            raise RuntimeError("v2 cluster insert returned no row")
        return int(rows[0]["id"])

    def update_v2_cluster(
        self,
        cluster_id: int,
        *,
        centroid: list[float],
        article_count: int,
        last_active_at: str,
        representative_article_id: int,
    ) -> None:
        self.client.table("news_clusters").update(
            {
                "centroid": centroid,
                "article_count": article_count,
                "last_active_at": last_active_at,
                "representative_article_id": representative_article_id,
                "summary_status": "pending",
            }
        ).eq("id", cluster_id).execute()

    def save_v2_assignment(
        self,
        *,
        article_id: int,
        stock_code: str,
        cluster_id: int | None,
        status: str,
        llm_called: bool,
        candidate_count: int,
        reason: str,
        error_code: str | None,
    ) -> None:
        from experiments.exp_b_factual_summaries.assign_llm_v2 import (
            ASSIGN_V2_PROMPT_VERSION,
        )

        assigned_at = _now().isoformat() if cluster_id is not None else None
        retry_at = None
        if status == "pending_retry":
            retry_at = (
                _now() + timedelta(minutes=self.cfg.news_clustering_retry_minutes)
            ).isoformat()
        self.client.table("news_cluster_assignments").upsert(
            {
                "article_id": article_id,
                "stock_code": stock_code,
                "cluster_id": cluster_id,
                "kind": "company",
                "status": status,
                "llm_called": llm_called,
                "candidate_count": candidate_count,
                "assignment_reason": reason,
                "error_code": error_code,
                "prompt_version": ASSIGN_V2_PROMPT_VERSION if llm_called else None,
                "retry_count": 0,
                "next_retry_at": retry_at,
                "assigned_at": assigned_at,
            },
            on_conflict="article_id,stock_code",
        ).execute()

    # ------------------------------------------------------------------ 요약
    def get_v2_clusters(self, *, only_unsummarized: bool = False) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        offset = 0
        page = 1000
        while True:
            q = (
                self.client.table("news_clusters")
                .select("id,stock_code,summary_status,article_count")
                .eq("clustering_version", self.version)
            )
            if only_unsummarized:
                q = q.neq("summary_status", "success")
            resp = q.order("id").range(offset, offset + page - 1).execute()
            rows = resp.data or []
            out.extend(rows)
            if len(rows) < page:
                break
            offset += page
        return out

    def get_v2_cluster_articles(self, cluster_id: int) -> list[dict[str, Any]]:
        resp = (
            self.client.table("news_cluster_assignments")
            .select("articles!inner(id,title,description,body,press,published_at)")
            .eq("cluster_id", cluster_id)
            .in_("status", ["assigned_new", "assigned_existing"])
            .order("assigned_at")
            .execute()
        )
        return [r["articles"] for r in resp.data or [] if r.get("articles")]

    def save_v2_summary(
        self, cluster_id: int, parsed: dict[str, Any], meta: dict[str, Any], retry_count: int
    ) -> None:
        from experiments.exp_b_factual_summaries import config as cluster_cfg

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

    # -------------------------------------------------------------- 검사/활성화
    def count_pending_roles(self) -> int:
        """아직 현재 버전으로 분류 안 된 relevant pair 수(0이어야 활성화 가능)."""
        resp = (
            self.client.table("article_stocks")
            .select("article_id", count="exact")
            .eq("relevance", "relevant")
            .or_(f"role_version.is.null,role_version.neq.{self.version}")
            .limit(1)
            .execute()
        )
        return int(resp.count or 0)

    def count_unsummarized_v2(self) -> int:
        resp = (
            self.client.table("news_clusters")
            .select("id", count="exact")
            .eq("clustering_version", self.version)
            .neq("summary_status", "success")
            .limit(1)
            .execute()
        )
        return int(resp.count or 0)

    def get_active_version(self) -> str:
        resp = (
            self.client.table("news_pipeline_state").select("active_version").eq("id", 1).execute()
        )
        rows = resp.data or []
        return rows[0]["active_version"] if rows else ""

    def activate_v2(self, run_key: str) -> None:
        prev = self.get_active_version()
        self.client.table("news_pipeline_state").update(
            {
                "active_version": self.version,
                "active_run_key": run_key,
                "activated_at": _now().isoformat(),
                "previous_version": prev,
            }
        ).eq("id", 1).execute()
