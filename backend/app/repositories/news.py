"""Supabase persistence for idempotent news collection and crawl state."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from typing import Any, TypeVar

from supabase import Client

from app.core.config import Settings
from app.schemas.news import CrawlResult, NewsSearchItem
from app.services.relevance import STOCK_MENTION_RULES, classify_stock_relevance
from app.sources.news_utils import canonicalize_url
from app.sources.publishers import publisher_from_url

T = TypeVar("T")


def _batched(items: list[T], size: int) -> Iterable[list[T]]:
    for start in range(0, len(items), size):
        yield items[start : start + size]


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


class NewsRepository:
    """Store articles once and attach them to any number of stocks."""

    def __init__(self, client: Client, cfg: Settings):
        self.client = client
        self.cfg = cfg

    def upsert_search_items(
        self,
        *,
        stock_code: str,
        query: str,
        items: list[NewsSearchItem],
    ) -> dict[str, int]:
        deduplicated: dict[str, NewsSearchItem] = {}
        for item in items:
            deduplicated.setdefault(canonicalize_url(item.original_url), item)

        linked = 0
        for url_batch in _batched(list(deduplicated), self.cfg.supabase_batch_size):
            article_payloads = []
            for canonical_url in url_batch:
                item = deduplicated[canonical_url]
                article_payloads.append(
                    {
                        "canonical_url": canonical_url,
                        "original_url": item.original_url,
                        "naver_url": item.naver_url or None,
                        "title": item.title,
                        "description": item.description or None,
                        "press": publisher_from_url(item.original_url),
                        "published_at": item.published_at,
                    }
                )

            response = (
                self.client.table("articles")
                .upsert(article_payloads, on_conflict="canonical_url")
                .execute()
            )
            rows = response.data or []
            article_ids = {
                row["canonical_url"]: row["id"]
                for row in rows
                if row.get("canonical_url") and row.get("id") is not None
            }
            missing_urls = set(url_batch) - set(article_ids)
            if missing_urls:
                lookup = (
                    self.client.table("articles")
                    .select("id,canonical_url")
                    .in_("canonical_url", list(missing_urls))
                    .execute()
                )
                article_ids.update(
                    {
                        row["canonical_url"]: row["id"]
                        for row in (lookup.data or [])
                        if row.get("canonical_url") and row.get("id") is not None
                    }
                )
            if len(article_ids) != len(url_batch):
                raise RuntimeError(
                    f"Supabase returned {len(article_ids)}/{len(url_batch)} article ids"
                )

            links = [
                {
                    "article_id": article_ids[canonical_url],
                    "stock_code": stock_code,
                    "matched_query": query,
                }
                for canonical_url in url_batch
            ]
            self.client.table("article_stocks").upsert(
                links,
                on_conflict="article_id,stock_code",
            ).execute()
            linked += len(links)

        return {"received": len(items), "unique": len(deduplicated), "linked": linked}

    def reset_stale_processing(self, stale_after_minutes: int = 30) -> int:
        cutoff = (_utc_now() - timedelta(minutes=stale_after_minutes)).isoformat()
        response = (
            self.client.table("articles")
            .update(
                {
                    "crawl_status": "failed",
                    "fail_reason": "stale processing state recovered",
                    "next_retry_at": _utc_now().isoformat(),
                }
            )
            .eq("crawl_status", "processing")
            .lt("last_attempt_at", cutoff)
            .execute()
        )
        return len(response.data or [])

    def get_crawl_candidates(self, limit: int) -> list[dict[str, Any]]:
        fields = (
            "id,original_url,title,crawl_status,crawl_attempts,last_attempt_at,next_retry_at"
        )
        pending = (
            self.client.table("articles")
            .select(fields)
            .eq("crawl_status", "pending")
            .lt("crawl_attempts", self.cfg.max_crawl_retries)
            .order("id")
            .limit(limit)
            .execute()
        )
        candidates = list(pending.data or [])
        if len(candidates) >= limit:
            return candidates

        failed = (
            self.client.table("articles")
            .select(fields)
            .eq("crawl_status", "failed")
            .lt("crawl_attempts", self.cfg.max_crawl_retries)
            .order("next_retry_at")
            .limit(1000)
            .execute()
        )
        now = _utc_now()
        for row in failed.data or []:
            next_retry_at = _parse_timestamp(row.get("next_retry_at"))
            if next_retry_at is None or next_retry_at <= now:
                candidates.append(row)
            if len(candidates) >= limit:
                break
        return candidates

    def seconds_until_next_retry(self) -> float | None:
        response = (
            self.client.table("articles")
            .select("crawl_attempts,next_retry_at")
            .eq("crawl_status", "failed")
            .lt("crawl_attempts", self.cfg.max_crawl_retries)
            .order("next_retry_at")
            .limit(1000)
            .execute()
        )
        now = _utc_now()
        waits = []
        for row in response.data or []:
            retry_at = _parse_timestamp(row.get("next_retry_at"))
            if retry_at is None:
                return 0.0
            waits.append(max(0.0, (retry_at - now).total_seconds()))
        return min(waits) if waits else None

    def mark_attempt_started(self, article_id: int, attempts: int) -> None:
        self.client.table("articles").update(
            {
                "crawl_status": "processing",
                "crawl_attempts": attempts,
                "last_attempt_at": _utc_now().isoformat(),
                "next_retry_at": None,
                "fail_reason": None,
            }
        ).eq("id", article_id).execute()

    def mark_crawl_result(self, article_id: int, attempts: int, result: CrawlResult) -> None:
        now = _utc_now()
        if result.ok:
            payload: dict[str, Any] = {
                "crawl_status": "success",
                "body": result.body,
                "final_url": result.final_url or result.requested_url,
                "press": result.publisher or publisher_from_url(result.final_url),
                "http_status": result.status_code,
                "crawled_at": now.isoformat(),
                "next_retry_at": None,
                "fail_reason": None,
            }
            if result.title:
                payload["title"] = result.title
        elif result.skipped:
            payload = {
                "crawl_status": "skipped",
                "final_url": result.final_url or None,
                "press": result.publisher or None,
                "http_status": result.status_code,
                "fail_reason": result.error,
                "next_retry_at": None,
            }
        else:
            retry_at = None
            if attempts < self.cfg.max_crawl_retries:
                retry_at = (now + timedelta(minutes=self.cfg.failed_retry_minutes)).isoformat()
            payload = {
                "crawl_status": "failed",
                "final_url": result.final_url or None,
                "press": result.publisher or None,
                "http_status": result.status_code,
                "fail_reason": result.error,
                "next_retry_at": retry_at,
            }
        self.client.table("articles").update(payload).eq("id", article_id).execute()

    def classify_pending_relevance(self, *, dry_run: bool = False) -> dict[str, Any]:
        """Finalize pending article-stock links using stored title/body/description."""

        overall: dict[str, Any] = {
            "scanned": 0,
            "relevant": 0,
            "irrelevant": 0,
            "deferred": 0,
            "updated": 0,
            "stocks": {},
        }
        page_size = 250
        for stock_code, rule in STOCK_MENTION_RULES.items():
            rows: list[dict[str, Any]] = []
            offset = 0
            while True:
                response = (
                    self.client.table("article_stocks")
                    .select(
                        "article_id,stock_code,matched_query,"
                        "articles!inner(title,description,body,crawl_status,crawl_attempts)"
                    )
                    .eq("stock_code", stock_code)
                    .eq("relevance", "pending")
                    .order("article_id")
                    .range(offset, offset + page_size - 1)
                    .execute()
                )
                batch = response.data or []
                rows.extend(batch)
                if len(batch) < page_size:
                    break
                offset += page_size

            stock_summary = {
                "name": rule.name,
                "scanned": len(rows),
                "relevant": 0,
                "irrelevant": 0,
                "deferred": 0,
                "updated": 0,
            }
            updates: list[dict[str, Any]] = []
            for row in rows:
                article = row.get("articles") or {}
                decision = classify_stock_relevance(
                    stock_code=stock_code,
                    title=article.get("title"),
                    body=article.get("body"),
                    description=article.get("description"),
                )
                crawl_status = article.get("crawl_status")
                crawl_attempts = int(article.get("crawl_attempts") or 0)
                crawl_is_final = crawl_status in {"success", "skipped"} or (
                    crawl_status == "failed" and crawl_attempts >= self.cfg.max_crawl_retries
                )
                if decision.relevance == "irrelevant" and not crawl_is_final:
                    stock_summary["deferred"] += 1
                    continue

                stock_summary[decision.relevance] += 1
                updates.append(
                    {
                        "article_id": row["article_id"],
                        "stock_code": stock_code,
                        "matched_query": row.get("matched_query"),
                        "relevance": decision.relevance,
                        "mention_count": decision.mention_count,
                        "relevance_reason": decision.reason,
                    }
                )

            if not dry_run:
                for update_batch in _batched(updates, self.cfg.supabase_batch_size):
                    self.client.table("article_stocks").upsert(
                        update_batch,
                        on_conflict="article_id,stock_code",
                    ).execute()
                stock_summary["updated"] = len(updates)

            overall["stocks"][stock_code] = stock_summary
            for key in ("scanned", "relevant", "irrelevant", "deferred", "updated"):
                overall[key] += stock_summary[key]
        return overall

    def get_stock_summary(self, stock_code: str) -> dict[str, Any]:
        rows: list[dict[str, Any]] = []
        offset = 0
        page_size = 500
        while True:
            response = (
                self.client.table("article_stocks")
                .select("article_id,relevance,articles!inner(published_at,crawl_status)")
                .eq("stock_code", stock_code)
                .range(offset, offset + page_size - 1)
                .execute()
            )
            batch = response.data or []
            rows.extend(batch)
            if len(batch) < page_size:
                break
            offset += page_size

        dates = [
            row["articles"]["published_at"]
            for row in rows
            if row.get("articles") and row["articles"].get("published_at")
        ]
        statuses: dict[str, int] = {}
        relevance: dict[str, int] = {}
        for row in rows:
            article = row.get("articles") or {}
            status = article.get("crawl_status", "unknown")
            statuses[status] = statuses.get(status, 0) + 1
            label = row.get("relevance", "unknown")
            relevance[label] = relevance.get(label, 0) + 1
        return {
            "stock_code": stock_code,
            "stored": len(rows),
            "oldest_published_at": min(dates) if dates else None,
            "crawl_statuses": statuses,
            "relevance": relevance,
        }
