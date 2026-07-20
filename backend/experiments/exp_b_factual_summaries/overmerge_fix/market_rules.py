"""시황(market-wide) 기사 판별 규칙 — 투명한 규칙 기반 스코어.

prompt.md 실험 A 요구사항:
- 시장 키워드 하나 포함됐다는 이유만으로 판별하지 않는다(스코어 조합).
- 시장 주체 + 시장 움직임 + 수급 표현을 가점, 회사 고유 사건 표현을 감점.

market_score(title, description) -> float 를 계산하고, is_market_wide 로
임계값 판정한다. 이 규칙은 baseline 지표 계산과 실험 A/C 에서 동일하게 재사용한다.
"""

from __future__ import annotations

import re

# 시장 주체(시장 전체를 지칭) — 있으면 시황일 개연성이 크다.
MARKET_SUBJECT = ["코스피", "코스닥", "국내 증시", "국내증시", "뉴욕증시", "나스닥", "다우", "증시"]

# 시장 움직임 표현 — 장 전체의 등락/이벤트.
# 흔한 등락 표현(하락/상승/약세/강세/반등/회복/출발)까지 포함해야 시황을 제대로 잡는다.
# 이 표현들은 시장 주체(코스피 등)와 함께 있어야 가점되므로(주체 없으면 움직임만으론
# 부족) 회사 이벤트 기사를 오분류할 위험은 낮다.
MARKET_MOVE = [
    "장중",
    "장초반",
    "장 초반",
    "장전",
    "마감",
    "개장",
    "급락",
    "급등",
    "사이드카",
    "서킷브레이커",
    "패닉",
    "출렁",
    "브리핑",
    "시황",
    "선 회복",
    "선 붕괴",
    "선 돌파",
    "약세",
    "강세",
    "반등",
    "폭락",
    "폭등",
    "하락 마감",
    "상승 마감",
    "하락 출발",
    "상승 출발",
    "순매도",
    "순매수",
]

# 수급 표현 — 시장 전체 자금 흐름.
MARKET_FLOW = [
    "외국인 순매도",
    "외국인 매도",
    "기관 매수",
    "기관 매도",
    "외국인 순매수",
    "프로그램 매매",
]

# 회사 고유 사건 표현 — 있으면 특정 기업 이벤트라 시황이 아닐 개연성이 크다(감점).
COMPANY_EVENT = [
    "계약",
    "착공",
    "인수",
    "합병",
    "공급",
    "출시",
    "투자 발표",
    "임단협",
    "임협",
    "파업",
    "수주",
    "지분",
    "실적",
    "신제품",
    "리콜",
    "협약",
    "MOU",
    "특허",
    "증설",
    "공장",
    "배당",
    "자사주",
    "유상증자",
]


# 비사건형 투자정보(info) 표지 — 특정 기업의 '사건'이 아니라 시장/수급/추천/순위/
# 데이터성 기사. 이런 기사가 company 클러스터에 섞이면 서로 다른 종목 사건을 잇는
# 다리가 되어 over-merge 를 만든다(prompt: 인기 검색 종목·추천 종목·종목 순위·
# 여러 종목 나열·반도체/ADR 전망 등). 정규식으로 판별한다.
INFO_PATTERNS = [
    # 인기 검색 / 데이터랩 / 검색 종목
    r"인기\s*검색",
    r"데이터랩",
    r"검색\s*(종목|어)",
    # 초고수 / 고수의 선택
    r"초고수",
    r"\d+%\s*(초)?고수",
    # 순위 / TOP / 상위 / 선호도 / 가장 많이 담은
    r"순위",
    r"TOP\s*\d",
    r"상위\s*\d+\s*(종목|선)",
    r"선호(도|\s*종목)",
    r"많이\s*(담|산|매수)",
    r"가장\s*많이",
    r"20選|20선",
    # 추천 / 유망 / 주목 / 관심 종목, 이 종목/이 주식
    r"(추천|유망|주목|관심|기대)\s*종목",
    r"이\s*(종목|주식)",
    r"살\s*만한",
    # 거래소 수급 동향(특정 종목 사건 아님)
    r"거래소\s*(외국인|기관|개인)",
    r"(외국인|기관|개인|외인)[^ ]{0,4}\s*(집중\s*)?(순)?(매수|매도)",
    r"집중\s*(매수|매도)",
    r"폭풍\s*(매수|매도)",
    r"차익\s*실현",
    r"포트폴리오",
    r"GPIF|국민연금|연기금",
    # 전망 / 프리뷰 / 프리마켓 / ADR / 브리핑 / 리뷰 (비사건형 전망)
    r"ADR",
    r"프리(뷰|마켓|장)",
    r"브리핑",
    r"리뷰",
    r"전망(치|은|이|을)?\s*$|전망\b",
    # 특징주 / 특징 포착
    r"특징주",
    r"특징\s*포착",
    # 매매 동향 서술(사자/팔자/담고/샀다/팔았다)
    r"사자|팔자",
    r"담(고|았|은)",
    r"(샀|팔았)다",
    # 세대/집단 투자 정보
    r"\d+[·\-]\d+\s*(세대|은|대)",
    r"청년\s*세대",
    r"더블배거",
    # 개별 종목 일일 시세/주가 브리핑(사건 아님, 매일 반복) —
    # "주가, 7월 N일 장중 XX원 N% 하락", "장중 강보합세", "N거래일 하락세" 등
    r"주가[,·\s].*(상승|하락|강세|약세|보합|반등|급등|급락)",
    r"주가[,·\s].*\d+\.?\d*\s*%",
    r"장\s*(중|초반|후반|막판).*(상승|하락|강세|약세|보합|등락|변동)",
    r"\d+\s*거래일.*(상승|하락|반등|약세|강세)",
    r"동적\s*VI|정적\s*VI|변동성\s*완화",
    r"강보합|약보합|보합세",
    r"주가\s*흐름|주가\s*향방|향방은",
    r"[가-힣]+주\s*(전반|일제히|동반|약세|강세|급락|급등|털썩|혼조)",  # 원전주/반도체주 섹터 등락
    r"\d+원선?\s*(회복|이탈|위협|붕괴|돌파|중심)",
    # 산업 전망/논평/기획성(특정 기업의 발표가 아니라 업황·테마 해설) —
    # cid1140/1144 처럼 여러 사건이 완만히 이어붙는 '조선/방산 업황' 기사.
    r"만평",
    r"낙수효과",
    r"베이스캠프",
    r"모멘텀",
    r"랠리",
    r"양극화",
    r"[Kk]-?조선|[Kk]-?방산|[Kk]-?주식|[Kk]-?배터리",
    r"빅\s*\d",  # 조선 빅3, 배터리 빅3
    r"업황|업계\s*(전반|동향|판도)",
    r"시험대|재평가|기대감\s*(부각|확산)",
    r"쏠린\s*눈|주목받|주목한다|이목",
    r"남는\s*장사|진짜\s*무기|쫄\s*필요",  # 논평성 제목투
]
_INFO_RE = [re.compile(p) for p in INFO_PATTERNS]

# 여러 종목을 나열(가운뎃점·쉼표로 3개 이상 회사/티커)하면 비사건형 투자정보 개연성↑.
_MULTI_STOCK_RE = re.compile(r"[가-힣A-Za-z]{2,}[·,]\s*[가-힣A-Za-z]{2,}[·,]\s*[가-힣A-Za-z]{2,}")


def _count_hits(text: str, keywords: list[str]) -> int:
    return sum(1 for k in keywords if k in text)


def info_score(title: str, description: str = "") -> int:
    """비사건형 투자정보 표지 개수(제목 기준). 클수록 info 개연성↑."""

    t = title or ""
    n = sum(1 for r in _INFO_RE if r.search(t))
    if _MULTI_STOCK_RE.search(t):
        n += 1
    return n


def is_investment_info(title: str, description: str = "") -> bool:
    """비사건형 투자정보 기사 여부.

    - 회사 고유 사건 키워드(COMPANY_EVENT)가 있으면 사건형으로 보고 info 아님(안전장치).
    - 그 외에 info 표지가 1개 이상이면 info.
    시황(market_wide)과의 우선순위는 classify_kind 에서 정한다(market 우선).
    """

    t = title or ""
    d = description or ""
    if _count_hits(t + d, COMPANY_EVENT):
        return False
    return info_score(t, d) >= 1


def classify_kind(title: str, description: str = "") -> str:
    """기사 유형: 'market'(시황) | 'info'(비사건형 투자정보) | 'company'(기업 사건).

    우선순위: market > info > company.
    브리지 차단에서 market/info 는 company 클러스터에 붙지 않는다.
    """

    if is_market_wide(title, description):
        return "market"
    if is_investment_info(title, description):
        return "info"
    return "company"


def market_score(title: str, description: str = "") -> float:
    """시황성 점수. 제목 가중(x2) + description 가중(x1).

    구성:
      + 시장 주체 존재                → +1.0 (제목) / +0.5 (설명)
      + 시장 움직임 표현 존재         → +1.0 (제목) / +0.5 (설명)
      + 수급 표현 존재                → +0.5
      - 회사 고유 사건 표현 존재      → -1.5 (있으면 시황 아님으로 강하게 끌어내림)
    점수가 높을수록 시황일 개연성이 크다.
    """

    t = title or ""
    d = description or ""

    score = 0.0
    if _count_hits(t, MARKET_SUBJECT):
        score += 1.0
    if _count_hits(d, MARKET_SUBJECT):
        score += 0.5
    if _count_hits(t, MARKET_MOVE):
        score += 1.0
    if _count_hits(d, MARKET_MOVE):
        score += 0.5
    if _count_hits(t + d, MARKET_FLOW):
        score += 0.5

    if _count_hits(t + d, COMPANY_EVENT):
        score -= 1.5

    return score


# 판정 임계값: 시장 주체(+1) 와 시장 움직임(+1) 이 함께 있고 회사 이벤트가 없어야
# market_wide 로 본다. 즉 최소 2.0 이상.
MARKET_THRESHOLD = 2.0


def is_market_wide(title: str, description: str = "", threshold: float = MARKET_THRESHOLD) -> bool:
    return market_score(title, description) >= threshold


def market_day_bucket(published_at_iso: str) -> str:
    """거래일 경계용 날짜 버킷(YYYY-MM-DD). 서로 다른 거래일의 시황을
    무조건 연결하지 않도록 실험 A 에서 이 값을 클러스터 키에 반영한다."""

    return (published_at_iso or "")[:10]
