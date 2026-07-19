"""Data structures shared by news sources, jobs, and persistence."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class NewsSearchItem:
    """One normalized item returned by Naver News search."""

    title: str
    original_url: str
    naver_url: str
    description: str
    published_at: str


@dataclass(frozen=True, slots=True)
class NewsSearchResult:
    """One stock query result including pagination diagnostics."""

    query: str
    items: list[NewsSearchItem]
    pages_requested: int
    raw_items_received: int
    api_total: int


@dataclass(frozen=True, slots=True)
class CrawlResult:
    """Result of extracting an article body from its publisher URL."""

    ok: bool
    requested_url: str
    final_url: str = ""
    title: str = ""
    body: str = ""
    publisher: str = ""
    error: str = ""
    status_code: int | None = None
    skipped: bool = False
