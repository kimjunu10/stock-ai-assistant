"""Map publisher domains to stable Korean display names."""

from urllib.parse import urlsplit

PUBLISHER_BY_DOMAIN = {
    "yna.co.kr": "연합뉴스",
    "hankyung.com": "한국경제",
    "mk.co.kr": "매일경제",
    "sedaily.com": "서울경제",
    "edaily.co.kr": "이데일리",
    "mt.co.kr": "머니투데이",
    "news.mt.co.kr": "머니투데이",
    "asiae.co.kr": "아시아경제",
    "fnnews.com": "파이낸셜뉴스",
    "etnews.com": "전자신문",
    "news1.kr": "뉴스1",
    "chosun.com": "조선일보",
    "joongang.co.kr": "중앙일보",
    "donga.com": "동아일보",
    "zdnet.co.kr": "지디넷코리아",
    "thebell.co.kr": "더벨",
    "dealsite.co.kr": "딜사이트",
}


def publisher_from_url(url: str) -> str:
    """Return a friendly publisher name, falling back to the hostname."""

    host = urlsplit(url).netloc.lower().split(":", 1)[0]
    if host.startswith("www."):
        host = host[4:]

    for domain, publisher in PUBLISHER_BY_DOMAIN.items():
        if host == domain or host.endswith(f".{domain}"):
            return publisher
    return host or "알 수 없음"
