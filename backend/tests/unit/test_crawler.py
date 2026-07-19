from bs4 import BeautifulSoup

from app.sources.crawler import ArticleCrawler


def test_extract_fusion_body_reads_text_elements() -> None:
    html = """
    <script id="fusion-metadata">
    Fusion.globalContent={"content_elements":[
      {"type":"image","caption":"ignore"},
      {"type":"text","content":"첫 번째 <b>본문</b>"},
      {"type":"text","content":"두 번째 문단"}
    ]};Fusion.other={};
    </script>
    """

    body = ArticleCrawler._extract_fusion_body(BeautifulSoup(html, "html.parser"))

    assert body == "첫 번째 본문\n두 번째 문단"


def test_extract_script_json_body_reads_react_query_article() -> None:
    html = """
    <script>
    window["__RQ:test"] = window["__RQ:test"] || [];
    window["__RQ:test"].push({"state":{"data":{"articleContent":
      "<p>첫 번째 본문</p><p>두 번째 문단</p>"}}});
    </script>
    """

    body = ArticleCrawler._extract_script_json_body(
        BeautifulSoup(html, "html.parser")
    )

    assert body == "첫 번째 본문\n두 번째 문단"


def test_extract_script_json_body_reads_next_content_arrange() -> None:
    html = """
    <script id="__NEXT_DATA__" type="application/json">
    {"props":{"articleView":{"contentArrange":[
      {"type":"image","content":"사진 설명"},
      {"type":"text","content":"첫 번째 본문"},
      {"type":"text","content":"두 번째 문단"}
    ]}}}
    </script>
    """

    body = ArticleCrawler._extract_script_json_body(
        BeautifulSoup(html, "html.parser")
    )

    assert body == "첫 번째 본문\n두 번째 문단"


def test_extract_meta_refresh_url_resolves_absolute_target() -> None:
    html = """
    <html><head>
      <meta http-equiv="refresh" content="0;URL='/news/article/123'">
    </head></html>
    """

    target = ArticleCrawler._extract_meta_refresh_url(
        html,
        "https://m.example.com/news/redirect",
    )

    assert target == "https://m.example.com/news/article/123"


def test_extract_amp_url_resolves_official_alternate() -> None:
    html = """
    <html><head>
      <link rel="amphtml" href="/news/amp/123">
    </head></html>
    """

    target = ArticleCrawler._extract_amp_url(
        html,
        "https://www.example.com/news/123",
    )

    assert target == "https://www.example.com/news/amp/123"
