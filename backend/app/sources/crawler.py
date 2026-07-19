"""Article-body crawler retained from the validated local MVP."""

from __future__ import annotations

import json
import re
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

import requests
import trafilatura
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from app.core.config import Settings
from app.schemas.news import CrawlResult
from app.sources.news_utils import compact_whitespace
from app.sources.publishers import publisher_from_url

ARTICLE_SELECTORS = [
    "article",
    "#articleBody",
    "#article-body",
    "#articleBodyContents",
    "#newsEndContents",
    "#dic_area",
    ".article-body",
    ".article_body",
    ".article-view-content-div",
    ".newsct_article",
    ".news_cnt_detail_wrap",
    ".story-news.article",
    ".articletext2",
    ".detail_editor",
]

BOILERPLATE_PATTERNS = [
    re.compile(r"무단\s*전재.*재배포\s*금지"),
    re.compile(r"저작권자.*금지"),
    re.compile(r"기자\s*\([^)]*@[^)]*\)"),
    re.compile(r"제보는\s*카카오톡"),
    re.compile(r"^(구독하기|기사\s*스크랩|댓글|글자\s*크기|앱에서\s*읽기|로그인)$"),
]

SHORT_ARTICLE_HOSTS = {
    "www.bigtanews.co.kr",
    "www.edaily.co.kr",
    "www.ulsanpress.net",
}

PREFERRED_BODY_SELECTORS = {
    "www.edaily.co.kr": ".news_body",
    "www.ulsanpress.net": "#article-view-content-div",
}


class ArticleCrawler:
    """Respect robots.txt and extract article text through four fallbacks."""

    def __init__(self, cfg: Settings):
        self.cfg = cfg
        retry = Retry(
            total=1,
            connect=1,
            read=1,
            status=1,
            backoff_factor=0.5,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset({"GET"}),
            respect_retry_after_header=True,
        )
        self.session = requests.Session()
        self.session.mount("https://", HTTPAdapter(max_retries=retry))
        self.session.mount("http://", HTTPAdapter(max_retries=retry))
        self.session.headers.update(
            {
                "User-Agent": cfg.user_agent,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.6",
                "Cache-Control": "no-cache",
            }
        )
        self._robots_cache: dict[str, RobotFileParser | None] = {}

    def close(self) -> None:
        self.session.close()

    def _robots_allowed(self, url: str) -> tuple[bool, str]:
        if not self.cfg.respect_robots:
            return True, "robots 확인 비활성화"

        parts = urlsplit(url)
        base = f"{parts.scheme}://{parts.netloc}"
        robots_url = urljoin(base, "/robots.txt")

        if base not in self._robots_cache:
            try:
                response = self.session.get(
                    robots_url,
                    timeout=self.cfg.request_timeout_seconds,
                    allow_redirects=True,
                )
                if response.status_code == 404:
                    self._robots_cache[base] = None
                elif response.ok:
                    parser = RobotFileParser()
                    parser.set_url(robots_url)
                    parser.parse(response.text.splitlines())
                    self._robots_cache[base] = parser
                else:
                    self._robots_cache[base] = None
                    if self.cfg.robots_fail_closed:
                        return False, f"robots.txt 확인 실패 HTTP {response.status_code}"
            except requests.RequestException as exc:
                self._robots_cache[base] = None
                if self.cfg.robots_fail_closed:
                    return False, f"robots.txt 확인 실패: {exc}"

        parser = self._robots_cache.get(base)
        if parser is None:
            return True, "robots 규칙 없음/확인 실패"

        allowed = parser.can_fetch(self.cfg.user_agent, url)
        return allowed, "허용" if allowed else "robots.txt에서 차단"

    def crawl(self, url: str) -> CrawlResult:
        allowed, robots_reason = self._robots_allowed(url)
        if not allowed:
            return CrawlResult(
                ok=False,
                requested_url=url,
                error=robots_reason,
                skipped=True,
            )

        try:
            response = self.session.get(
                url,
                timeout=self.cfg.request_timeout_seconds,
                allow_redirects=True,
            )
            status_code = response.status_code
            response.raise_for_status()
        except requests.RequestException as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            return CrawlResult(
                ok=False,
                requested_url=url,
                error=f"HTTP 요청 실패: {exc}",
                status_code=status,
            )

        content_type = response.headers.get("Content-Type", "").lower()
        if "html" not in content_type and "xhtml" not in content_type:
            return CrawlResult(
                ok=False,
                requested_url=url,
                final_url=response.url,
                error=f"HTML 문서가 아님: {content_type}",
                status_code=status_code,
            )

        try:
            response.encoding = response.apparent_encoding or response.encoding
            html_text = response.text
            refresh_url = self._extract_meta_refresh_url(html_text, response.url)
            if refresh_url and refresh_url != response.url:
                refresh_allowed, refresh_reason = self._robots_allowed(refresh_url)
                if not refresh_allowed:
                    return CrawlResult(
                        ok=False,
                        requested_url=url,
                        final_url=refresh_url,
                        error=refresh_reason,
                        skipped=True,
                    )
                response = self.session.get(
                    refresh_url,
                    timeout=self.cfg.request_timeout_seconds,
                    allow_redirects=True,
                )
                status_code = response.status_code
                response.raise_for_status()
                refresh_content_type = response.headers.get("Content-Type", "").lower()
                if "html" not in refresh_content_type and "xhtml" not in refresh_content_type:
                    return CrawlResult(
                        ok=False,
                        requested_url=url,
                        final_url=response.url,
                        error=f"HTML 문서가 아님: {refresh_content_type}",
                        status_code=status_code,
                    )
                response.encoding = response.apparent_encoding or response.encoding
                html_text = response.text
            title = self._extract_title(html_text)
            body = self._extract_body(html_text, response.url)
            if len(body) < self.cfg.min_body_length:
                amp_url = self._extract_amp_url(html_text, response.url)
                amp_response = self._fetch_alternate_html(amp_url) if amp_url else None
                if amp_response is not None:
                    amp_body = self._extract_body(amp_response.text, amp_response.url)
                    if len(amp_body) > len(body):
                        response = amp_response
                        status_code = response.status_code
                        title = self._extract_title(response.text) or title
                        body = amp_body
            if len(body) < self.cfg.min_body_length:
                api_body = self._extract_publisher_api_body(response.url)
                if len(api_body) > len(body):
                    body = api_body
        except Exception as exc:  # noqa: BLE001 - isolate publisher-specific parser failures
            return CrawlResult(
                ok=False,
                requested_url=url,
                final_url=response.url,
                publisher=publisher_from_url(response.url),
                error=f"본문 파싱 실패: {type(exc).__name__}: {exc}",
                status_code=status_code,
            )

        minimum_body_length = self._minimum_body_length(response.url)
        if len(body) < minimum_body_length:
            return CrawlResult(
                ok=False,
                requested_url=url,
                final_url=response.url,
                title=title,
                publisher=publisher_from_url(response.url),
                error=(
                    f"본문 추출 길이가 너무 짧음({len(body)}자). "
                    "동적 렌더링·유료벽·사이트별 구조일 수 있음."
                ),
                status_code=status_code,
            )

        return CrawlResult(
            ok=True,
            requested_url=url,
            final_url=response.url,
            title=title,
            body=body,
            publisher=publisher_from_url(response.url),
            status_code=status_code,
        )

    def _minimum_body_length(self, url: str) -> int:
        host = urlsplit(url).netloc.lower()
        return 80 if host in SHORT_ARTICLE_HOSTS else self.cfg.min_body_length

    @staticmethod
    def _extract_meta_refresh_url(html_text: str, base_url: str) -> str:
        soup = BeautifulSoup(html_text, "html.parser")
        tag = soup.find(
            "meta",
            attrs={"http-equiv": lambda value: value and value.lower() == "refresh"},
        )
        if tag is None:
            return ""
        content = tag.get("content") or ""
        match = re.search(r"url\s*=\s*['\"]?([^'\";]+)", content, flags=re.IGNORECASE)
        return urljoin(base_url, match.group(1).strip()) if match else ""

    @staticmethod
    def _extract_amp_url(html_text: str, base_url: str) -> str:
        soup = BeautifulSoup(html_text, "html.parser")
        tag = soup.find(
            "link",
            rel=lambda value: value
            and "amphtml" in (value if isinstance(value, list) else [value]),
        )
        href = tag.get("href") if tag else None
        return urljoin(base_url, href.strip()) if isinstance(href, str) else ""

    def _fetch_alternate_html(self, url: str) -> requests.Response | None:
        allowed, _ = self._robots_allowed(url)
        if not allowed:
            return None
        try:
            response = self.session.get(
                url,
                timeout=self.cfg.request_timeout_seconds,
                allow_redirects=True,
            )
            response.raise_for_status()
        except requests.RequestException:
            return None
        content_type = response.headers.get("Content-Type", "").lower()
        if "html" not in content_type and "xhtml" not in content_type:
            return None
        response.encoding = response.apparent_encoding or response.encoding
        return response

    def _extract_publisher_api_body(self, url: str) -> str:
        """Use a publisher's public page API when its HTML is only an app shell."""

        parts = urlsplit(url)
        publisher_apis = {
            "biz.sbs.co.kr": (
                "https://apis.sbs.co.kr/play-api/1.0/sbs_newsmedia/",
                "https://biz.sbs.co.kr/",
            ),
            "news.cpbc.co.kr": (
                "https://apis.cpbc.co.kr/play-api/1.0/sbs_newsmedia/",
                "https://news.cpbc.co.kr/",
            ),
        }
        api_config = publisher_apis.get(parts.netloc.lower())
        if api_config is None:
            return ""
        article_match = re.search(r"/article(?:_hub)?/(\d+)(?:/|$)", parts.path)
        if article_match is None:
            return ""

        api_base_url, referer = api_config
        api_url = f"{api_base_url}{article_match.group(1)}"
        allowed, _ = self._robots_allowed(api_url)
        if not allowed:
            return ""
        try:
            response = self.session.get(
                api_url,
                timeout=self.cfg.request_timeout_seconds,
                headers={"Referer": referer},
            )
            response.raise_for_status()
            info = response.json().get("clip", {}).get("info", {})
        except (requests.RequestException, ValueError, AttributeError):
            return ""

        for field in ("contentdata", "synopsis"):
            value = info.get(field)
            if isinstance(value, str) and value.strip():
                text = BeautifulSoup(value, "html.parser").get_text("\n", strip=True)
                cleaned = self._clean_body(text)
                if cleaned:
                    return cleaned
        return ""

    @staticmethod
    def _extract_title(html_text: str) -> str:
        soup = BeautifulSoup(html_text, "html.parser")
        for attrs in ({"property": "og:title"}, {"name": "twitter:title"}):
            tag = soup.find("meta", attrs=attrs)
            if tag and tag.get("content"):
                return compact_whitespace(tag["content"])
        if soup.title and soup.title.string:
            return compact_whitespace(soup.title.string)
        return ""

    def _extract_body(self, html_text: str, url: str) -> str:
        candidates: list[str] = []
        extracted = trafilatura.extract(
            html_text,
            url=url,
            include_comments=False,
            include_tables=False,
            favor_precision=True,
            deduplicate=True,
            output_format="txt",
        )
        if extracted:
            candidates.append(extracted)

        soup = BeautifulSoup(html_text, "html.parser")
        fusion_body = self._extract_fusion_body(soup)
        if fusion_body:
            candidates.append(fusion_body)

        script_json_body = self._extract_script_json_body(soup)
        if script_json_body:
            candidates.append(script_json_body)

        json_ld_body = self._extract_json_ld_body(soup)
        if json_ld_body:
            candidates.append(json_ld_body)

        for selector in ARTICLE_SELECTORS:
            node = soup.select_one(selector)
            if node:
                text = node.get_text("\n", strip=True)
                if text:
                    candidates.append(text)

        paragraph_text = "\n".join(
            paragraph
            for p in soup.find_all("p")
            if len(paragraph := p.get_text(" ", strip=True)) >= 30
        )
        if paragraph_text:
            candidates.append(paragraph_text)

        preferred_selector = PREFERRED_BODY_SELECTORS.get(urlsplit(url).netloc.lower())
        if preferred_selector:
            preferred_node = soup.select_one(preferred_selector)
            if preferred_node:
                preferred_body = self._clean_body(
                    preferred_node.get_text("\n", strip=True)
                )
                if preferred_body:
                    return preferred_body

        cleaned = [self._clean_body(value) for value in candidates]
        return max((value for value in cleaned if value), key=len, default="")

    @staticmethod
    def _extract_fusion_body(soup: BeautifulSoup) -> str:
        """Extract Arc/Fusion article elements used by publishers such as Chosun."""

        script = soup.select_one("#fusion-metadata")
        if script is None:
            return ""
        raw = script.string or script.get_text()
        marker = "Fusion.globalContent="
        marker_index = raw.find(marker)
        if marker_index < 0:
            return ""
        try:
            payload, _ = json.JSONDecoder().raw_decode(raw[marker_index + len(marker) :])
        except (json.JSONDecodeError, TypeError):
            return ""

        texts: list[str] = []

        def collect(element: object) -> None:
            if isinstance(element, list):
                for item in element:
                    collect(item)
                return
            if not isinstance(element, dict):
                return

            element_type = element.get("type")
            content = element.get("content")
            if element_type in {"text", "header", "quote"} and isinstance(content, str):
                clean = BeautifulSoup(content, "html.parser").get_text(" ", strip=True)
                if clean:
                    texts.append(clean)
            for key in ("content_elements", "items"):
                collect(element.get(key))

        collect(payload.get("content_elements"))
        return "\n".join(texts)

    @staticmethod
    def _extract_script_json_body(soup: BeautifulSoup) -> str:
        """Read article text embedded in JSON state, including JTBC React Query data."""

        bodies: list[str] = []

        def collect(value: object) -> None:
            if isinstance(value, list):
                for item in value:
                    collect(item)
                return
            if not isinstance(value, dict):
                return
            arranged = value.get("contentArrange")
            if isinstance(arranged, list):
                paragraphs = [
                    item["content"]
                    for item in arranged
                    if isinstance(item, dict)
                    and item.get("type") == "text"
                    and isinstance(item.get("content"), str)
                    and item["content"].strip()
                ]
                if paragraphs:
                    bodies.append("\n".join(paragraphs))
            for key in ("articleInnerTextContent", "articleContent"):
                content = value.get(key)
                if isinstance(content, str) and content.strip():
                    text = BeautifulSoup(content, "html.parser").get_text("\n", strip=True)
                    if text:
                        bodies.append(text)
            for nested in value.values():
                collect(nested)

        decoder = json.JSONDecoder()
        for script in soup.find_all("script"):
            raw = script.string or script.get_text()
            if not any(
                marker in raw
                for marker in (
                    "articleContent",
                    "articleInnerTextContent",
                    "contentArrange",
                )
            ):
                continue
            if script.get("type") == "application/json":
                try:
                    collect(json.loads(raw))
                except json.JSONDecodeError:
                    pass
            for match in re.finditer(r"\.push\(", raw):
                try:
                    payload, _ = decoder.raw_decode(raw[match.end() :])
                except json.JSONDecodeError:
                    continue
                collect(payload)

        return max(bodies, key=len, default="")

    def _extract_json_ld_body(self, soup: BeautifulSoup) -> str:
        bodies: list[str] = []
        for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
            raw = script.string or script.get_text()
            if not raw.strip():
                continue
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                continue
            self._collect_article_bodies(data, bodies)
        return max(bodies, key=len, default="")

    def _collect_article_bodies(self, data: object, bodies: list[str]) -> None:
        if isinstance(data, dict):
            body = data.get("articleBody")
            if isinstance(body, str) and body.strip():
                bodies.append(body)
            for value in data.values():
                self._collect_article_bodies(value, bodies)
        elif isinstance(data, list):
            for value in data:
                self._collect_article_bodies(value, bodies)

    @staticmethod
    def _clean_body(text: str) -> str:
        lines: list[str] = []
        seen: set[str] = set()
        for raw_line in compact_whitespace(text).splitlines():
            line = raw_line.strip()
            if not line or len(line) < 2:
                continue
            if any(pattern.search(line) for pattern in BOILERPLATE_PATTERNS):
                continue
            normalized = re.sub(r"\s+", " ", line)
            if normalized in seen:
                continue
            seen.add(normalized)
            lines.append(normalized)
        return "\n".join(lines).strip()
