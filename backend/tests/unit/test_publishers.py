from app.sources.publishers import hostname_from_url, is_allowed_news_url, publisher_from_url


def test_hostname_from_url_normalizes_www_and_case() -> None:
    assert hostname_from_url("https://WWW.HANKYUNG.COM/article/1") == "hankyung.com"


def test_allowed_news_url_accepts_core_and_subdomains() -> None:
    assert is_allowed_news_url("https://yna.co.kr/view/AKR1")
    assert is_allowed_news_url("https://view.asiae.co.kr/article/1")
    assert is_allowed_news_url("https://biz.heraldcorp.com/article/1")
    assert is_allowed_news_url("https://news.kbs.co.kr/news/view.do?ncd=1")


def test_allowed_news_url_accepts_added_financial_and_doosan_sources() -> None:
    assert is_allowed_news_url("https://biz.sbs.co.kr/article/1")
    assert is_allowed_news_url("https://news.einfomax.co.kr/news/articleView.html?idxno=1")
    assert is_allowed_news_url("https://theguru.co.kr/news/article.html?no=1")
    assert is_allowed_news_url("https://newstnt.com/news/articleView.html?idxno=1")


def test_allowed_news_url_rejects_unlisted_and_spoofed_domains() -> None:
    assert not is_allowed_news_url("https://example.com/article/1")
    assert not is_allowed_news_url("https://hankyung.com.example.com/article/1")
    assert not is_allowed_news_url("not-a-url")


def test_publisher_names_cover_newly_allowed_sources() -> None:
    assert publisher_from_url("https://biz.sbs.co.kr/article/1") == "SBS Biz"
    assert publisher_from_url("https://biz.heraldcorp.com/article/1") == "헤럴드경제"
    assert publisher_from_url("https://theguru.co.kr/article/1") == "더구루"
