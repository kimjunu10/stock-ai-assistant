from app.sources.news_utils import canonicalize_url, strip_html


def test_canonicalize_url_removes_tracking_and_fragment() -> None:
    url = "https://www.example.com/news/1/?utm_source=naver&b=2&a=1#section"

    assert canonicalize_url(url) == "https://example.com/news/1?a=1&b=2"


def test_strip_html_decodes_naver_markup() -> None:
    assert strip_html("<b>삼성전자</b> &amp; 반도체") == "삼성전자 & 반도체"
