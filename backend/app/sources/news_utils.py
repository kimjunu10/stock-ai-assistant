"""Normalization helpers retained from the validated news MVP."""

import html
import re
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from bs4 import BeautifulSoup

TRACKING_PARAMS = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "fbclid",
    "gclid",
    "n_media",
    "n_query",
    "n_rank",
    "n_ad_group",
    "n_ad",
}


def strip_html(value: str) -> str:
    """Remove Naver search markup and decode HTML entities."""

    soup = BeautifulSoup(html.unescape(value or ""), "html.parser")
    return " ".join(soup.get_text(" ", strip=True).split())


def canonicalize_url(url: str) -> str:
    """Normalize an article URL for database-level deduplication."""

    parts = urlsplit(url.strip())
    scheme = (parts.scheme or "https").lower()
    host = parts.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    path = re.sub(r"/{2,}", "/", parts.path or "/")
    if path != "/":
        path = path.rstrip("/")
    query_items = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if key.lower() not in TRACKING_PARAMS
    ]
    query = urlencode(sorted(query_items), doseq=True)
    return urlunsplit((scheme, host, path, query, ""))


def parse_naver_date(value: str) -> datetime:
    """Parse RFC-2822 dates returned by Naver and normalize to UTC."""

    parsed = parsedate_to_datetime(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def compact_whitespace(text: str) -> str:
    """Collapse noisy horizontal whitespace while preserving paragraphs."""

    text = text.replace("\u00a0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()
