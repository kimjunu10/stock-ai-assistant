"""Paginated Naver News search adapter."""

from __future__ import annotations

from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from app.core.config import Settings
from app.schemas.news import NewsSearchItem, NewsSearchResult
from app.sources.news_utils import canonicalize_url, parse_naver_date, strip_html

NAVER_NEWS_ENDPOINT = "https://openapi.naver.com/v1/search/news.json"
NAVER_MAX_START = 1000
NAVER_MAX_DISPLAY = 100


def _retrying_session() -> requests.Session:
    retry = Retry(
        total=2,
        connect=2,
        read=2,
        status=2,
        backoff_factor=1.0,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET"}),
        respect_retry_after_header=True,
    )
    session = requests.Session()
    session.mount("https://", HTTPAdapter(max_retries=retry))
    return session


class NaverNewsClient:
    """Fetch up to the 1,000 results exposed by Naver for one query."""

    def __init__(self, cfg: Settings, session: requests.Session | None = None):
        self.cfg = cfg
        self.session = session or _retrying_session()

    def close(self) -> None:
        self.session.close()

    def search_latest(self, query: str, max_results: int = 1000) -> NewsSearchResult:
        if not self.cfg.naver_client_id or not self.cfg.naver_client_secret:
            raise RuntimeError("NAVER_CLIENT_ID and NAVER_CLIENT_SECRET are required")

        target = min(max(1, max_results), NAVER_MAX_START)
        start = 1
        pages_requested = 0
        raw_items_received = 0
        api_total = 0
        deduplicated: dict[str, NewsSearchItem] = {}

        while start <= NAVER_MAX_START and raw_items_received < target:
            display = min(NAVER_MAX_DISPLAY, target - raw_items_received)
            payload = self._request_page(query=query, start=start, display=display)
            pages_requested += 1
            api_total = int(payload.get("total") or api_total or 0)
            raw_items = payload.get("items") or []
            if not isinstance(raw_items, list):
                raise RuntimeError(f"Naver returned a non-list items payload for {query}")
            if not raw_items:
                break

            raw_items_received += len(raw_items)
            for raw in raw_items:
                item = self._parse_item(raw)
                if item is None:
                    continue
                canonical_url = canonicalize_url(item.original_url)
                deduplicated.setdefault(canonical_url, item)

            if len(raw_items) < display:
                break
            if api_total and start + display > min(api_total, NAVER_MAX_START):
                break
            start += display

        return NewsSearchResult(
            query=query,
            items=list(deduplicated.values()),
            pages_requested=pages_requested,
            raw_items_received=raw_items_received,
            api_total=api_total,
        )

    def _request_page(self, *, query: str, start: int, display: int) -> dict[str, Any]:
        response = self.session.get(
            NAVER_NEWS_ENDPOINT,
            headers={
                "X-Naver-Client-Id": self.cfg.naver_client_id,
                "X-Naver-Client-Secret": self.cfg.naver_client_secret,
                "User-Agent": self.cfg.user_agent,
            },
            params={
                "query": query,
                "display": display,
                "start": start,
                "sort": "date",
            },
            timeout=self.cfg.request_timeout_seconds,
        )
        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            detail = response.text[:500].replace("\n", " ")
            raise RuntimeError(
                f"Naver API failed for query={query!r}, start={start}, "
                f"status={response.status_code}: {detail}"
            ) from exc
        payload = response.json()
        if not isinstance(payload, dict):
            raise RuntimeError(f"Naver returned a non-object payload for {query}")
        return payload

    @staticmethod
    def _parse_item(raw: dict[str, Any]) -> NewsSearchItem | None:
        original_url = (raw.get("originallink") or raw.get("link") or "").strip()
        if not original_url.startswith(("http://", "https://")):
            return None
        try:
            published_at = parse_naver_date(raw.get("pubDate", "")).isoformat()
        except (TypeError, ValueError, OverflowError):
            return None
        return NewsSearchItem(
            title=strip_html(raw.get("title", "")),
            original_url=original_url,
            naver_url=(raw.get("link") or "").strip(),
            description=strip_html(raw.get("description", "")),
            published_at=published_at,
        )
