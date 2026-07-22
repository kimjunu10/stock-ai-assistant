"""Map publisher domains to stable Korean display names."""

from urllib.parse import urlsplit

CORE_NEWS_DOMAINS = {
    # 통신사
    "yna.co.kr",
    "newsis.com",
    "news1.kr",
    # 경제·증권
    "mk.co.kr",
    "hankyung.com",
    "sedaily.com",
    "edaily.co.kr",
    "mt.co.kr",
    "fnnews.com",
    "asiae.co.kr",
    "biz.chosun.com",
    "heraldcorp.com",
    "etoday.co.kr",
    "newspim.com",
    "biz.sbs.co.kr",
    "news.einfomax.co.kr",
    "wowtv.co.kr",
    "ebn.co.kr",
    "ajunews.com",
    "inews24.com",
    "dt.co.kr",
    "newsway.co.kr",
    "dailian.co.kr",
    # 종합지
    "chosun.com",
    "joongang.co.kr",
    "donga.com",
    "hani.co.kr",
    "khan.co.kr",
    "hankookilbo.com",
    "kmib.co.kr",
    "seoul.co.kr",
    # 방송
    "kbs.co.kr",
    "imnews.imbc.com",
    "news.sbs.co.kr",
    "ytn.co.kr",
    "jtbc.co.kr",
}

SPECIALIST_NEWS_DOMAINS = {
    # IT·전자
    "etnews.com",
    "ddaily.co.kr",
    "zdnet.co.kr",
    "bloter.net",
    # 자본시장·기업
    "thebell.co.kr",
    "dealsite.co.kr",
    "businesspost.co.kr",
    # 두산에너빌리티 원전·가스터빈·NDR 보강
    "theguru.co.kr",
    "newstnt.com",
}

PRIMARY_SOURCE_DOMAINS = {
    "dart.fss.or.kr",
    "krx.co.kr",
    "fsc.go.kr",
    "fss.or.kr",
    "motie.go.kr",
}

ALLOWED_NEWS_DOMAINS = frozenset(
    CORE_NEWS_DOMAINS | SPECIALIST_NEWS_DOMAINS | PRIMARY_SOURCE_DOMAINS
)

PUBLISHER_BY_DOMAIN = {
    "yna.co.kr": "연합뉴스",
    "newsis.com": "뉴시스",
    "news1.kr": "뉴스1",
    "hankyung.com": "한국경제",
    "mk.co.kr": "매일경제",
    "sedaily.com": "서울경제",
    "edaily.co.kr": "이데일리",
    "mt.co.kr": "머니투데이",
    "news.mt.co.kr": "머니투데이",
    "asiae.co.kr": "아시아경제",
    "fnnews.com": "파이낸셜뉴스",
    "heraldcorp.com": "헤럴드경제",
    "etoday.co.kr": "이투데이",
    "newspim.com": "뉴스핌",
    "biz.sbs.co.kr": "SBS Biz",
    "news.einfomax.co.kr": "연합인포맥스",
    "wowtv.co.kr": "한국경제TV",
    "ebn.co.kr": "EBN",
    "ajunews.com": "아주경제",
    "inews24.com": "아이뉴스24",
    "dt.co.kr": "디지털타임스",
    "newsway.co.kr": "뉴스웨이",
    "dailian.co.kr": "데일리안",
    "etnews.com": "전자신문",
    "ddaily.co.kr": "디지털데일리",
    "chosun.com": "조선일보",
    "joongang.co.kr": "중앙일보",
    "donga.com": "동아일보",
    "hani.co.kr": "한겨레",
    "khan.co.kr": "경향신문",
    "hankookilbo.com": "한국일보",
    "kmib.co.kr": "국민일보",
    "seoul.co.kr": "서울신문",
    "kbs.co.kr": "KBS",
    "imnews.imbc.com": "MBC",
    "news.sbs.co.kr": "SBS",
    "ytn.co.kr": "YTN",
    "jtbc.co.kr": "JTBC",
    "zdnet.co.kr": "지디넷코리아",
    "bloter.net": "블로터",
    "thebell.co.kr": "더벨",
    "dealsite.co.kr": "딜사이트",
    "businesspost.co.kr": "비즈니스포스트",
    "theguru.co.kr": "더구루",
}


def hostname_from_url(url: str) -> str:
    """Return a normalized hostname suitable for exact/suffix matching."""

    host = urlsplit(url).netloc.lower().split(":", 1)[0]
    return host[4:] if host.startswith("www.") else host


def is_allowed_news_url(url: str) -> bool:
    """Whether a URL belongs to the curated news/source domain set."""

    host = hostname_from_url(url)
    return bool(host) and any(
        host == domain or host.endswith(f".{domain}") for domain in ALLOWED_NEWS_DOMAINS
    )


def publisher_from_url(url: str) -> str:
    """Return a friendly publisher name, falling back to the hostname."""

    host = hostname_from_url(url)

    for domain, publisher in PUBLISHER_BY_DOMAIN.items():
        if host == domain or host.endswith(f".{domain}"):
            return publisher
    return host or "알 수 없음"
