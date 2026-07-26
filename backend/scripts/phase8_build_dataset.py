"""Phase 8: 160문항 평가셋·정답 라벨 생성 (read-only).

정답 라벨을 사람이 옮겨 적지 않는다 — 실제 DB(financials·research_reports·
structured_disclosures·news_clusters·rag_terms)를 조회해 기준 데이터에서 만든다.
RAG 가 생성한 답변은 정답으로 쓰지 않는다.

원본에서 확인되지 않는 항목은 임의로 채우지 않고 review_status=needs_manual_review
로 남긴다.

실행:
    cd backend
    .venv/bin/python scripts/phase8_build_dataset.py
산출: docs/rag/phase_8/eval/devset.json, holdout.json
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.client import get_supabase_client  # noqa: E402
from app.eval.schema import TYPE_QUOTA, EvalCase, EvalSuite  # noqa: E402

OUT_DIR = Path(__file__).resolve().parents[1] / "docs" / "rag" / "phase_8" / "eval"

REPRT_LABEL = {"11013": "1분기", "11012": "반기", "11014": "3분기", "11011": "연간"}
PERIOD_KEY = {"11013": "q1", "11012": "half", "11014": "q3", "11011": "annual"}
AMOUNT_LABEL = {"cumulative": "누적", "quarter": "단독", "point_in_time": "시점"}

# 홀드아웃 비율(§6): 개발 120 / 홀드아웃 40.
HOLDOUT_RATIO = 0.25


def _fetch_all(client, table: str, columns: str, **filters) -> list[dict]:
    q = client.table(table).select(columns)
    for k, v in filters.items():
        q = q.eq(k, v)
    return q.execute().data or []


def load_reference(client) -> dict:
    """정답 라벨의 근거가 될 실제 데이터를 읽는다."""
    stocks = {s["code"]: s["name"] for s in _fetch_all(client, "stocks", "code,name")}

    fin = (
        client.table("financials")
        .select("stock_code,bsns_year,reprt_code,fs_div,account_nm,thstrm_amount,amount_type")
        .in_("account_nm", ["매출액", "영업이익", "당기순이익", "부채총계", "자산총계"])
        .execute()
        .data
        or []
    )

    reports = (
        client.table("research_reports")
        .select(
            "id,stock_code,broker,title,report_date,investment_opinion,"
            "target_price,target_price_status,target_price_source_page,page_count"
        )
        .eq("target_price_status", "stated")
        .order("report_date", desc=True)
        .limit(60)
        .execute()
        .data
        or []
    )

    clusters = (
        client.table("news_clusters")
        .select("id,stock_code,summary_title,first_published_at,sentiment_label,article_count,kind")
        .eq("summary_status", "success")
        .gte("article_count", 5)
        .order("first_published_at", desc=True)
        .limit(80)
        .execute()
        .data
        or []
    )

    # (종목, 공시유형) 조합을 고르게 확보한다. 최근순 일괄 조회로는 특정 조합이
    # 통째로 빠져(배당·자기주식이 최근 목록을 채움) 20문항을 못 만든다.
    disc_types = (
        client.table("structured_disclosures").select("stock_code,event_type").execute().data or []
    )
    combos = sorted({(d["stock_code"], d["event_type"]) for d in disc_types})
    disc: list[dict] = []
    for code, event_type in combos:
        rows = (
            client.table("structured_disclosures")
            .select("stock_code,rcept_no,event_type,announced_at,summary_text,bsns_year")
            .eq("stock_code", code)
            .eq("event_type", event_type)
            .order("announced_at", desc=True)
            .limit(1)
            .execute()
            .data
            or []
        )
        disc.extend(rows)

    terms = (
        client.table("rag_terms")
        .select("term")
        .eq("is_active", True)
        .in_(
            "term",
            [
                "주가수익비율",
                "주가순자산비율",
                "자기자본이익률",
                "영업이익",
                "당기순이익",
                "부채비율",
                "공매도",
                "유상증자",
                "기준금리",
                "인플레이션",
                "상장지수펀드",
                "자기주식",
                "배당할인모형",
                "변동금리",
                "실효환율",
            ],
        )
        .execute()
        .data
        or []
    )
    return {
        "stocks": stocks,
        "financials": fin,
        "reports": reports,
        "clusters": clusters,
        "disclosures": disc,
        "terms": [t["term"] for t in terms],
    }


def _fin_lookup(fin: list[dict], code: str, year: str, reprt: str, amount: str, acct: str):
    for r in fin:
        if (
            r["stock_code"] == code
            and r["bsns_year"] == year
            and r["reprt_code"] == reprt
            and r["amount_type"] == amount
            and r["account_nm"] == acct
        ):
            return r
    return None


def _has_final_consonant(word: str) -> bool:
    """마지막 글자에 받침이 있는지(조사 선택용). 한글이 아니면 없는 것으로 본다."""
    if not word:
        return False
    ch = word[-1]
    if not ("가" <= ch <= "힣"):
        return False
    return (ord(ch) - 0xAC00) % 28 != 0


def _josa(word: str, with_final: str, without_final: str) -> str:
    """받침 유무에 따라 조사를 고른다('공매도가' / '당기순이익이')."""
    return with_final if _has_final_consonant(word) else without_final


def build_terms(ref: dict) -> list[EvalCase]:
    """금융용어 15문항. 정답 근거 = rag_terms 에 실제 존재하는 표제어."""
    phrasings = [
        "{t}{i} 뭐야?",
        "{t} 쉽게 설명해줘",
        "{t}{i} 무슨 뜻이야?",
        "주식 처음인데 {t} 개념 알려줘",
        "{t}{n} 어떻게 계산해?",
    ]
    cases = []
    for i, term in enumerate(ref["terms"][:15]):
        cases.append(
            EvalCase(
                id=f"term-{i + 1:02d}",
                type="금융용어",
                question=phrasings[i % len(phrasings)].format(
                    t=term,
                    i=_josa(term, "이", "가"),
                    n=_josa(term, "은", "는"),
                ),
                required_tools=["lookup_financial_term"],
                forbidden_tools=[
                    "get_financial_facts",
                    "search_news",
                    "search_research_reports",
                    "get_stock_prices",
                ],
                expected_args={"lookup_financial_term": {"term_contains": term}},
                gold_sources=[{"source_type": "term", "source_id": f"term:{term}", "ref": term}],
                allowed_source_types=["term"],
                review_status="confirmed",
                label_basis=f"rag_terms 에 표제어 '{term}' 실재(is_active=true)",
            )
        )
    return cases


def build_financials(ref: dict) -> list[EvalCase]:
    """정확한 재무 숫자 25문항. 정답 = financials 실제 행(값은 실행기가 DB 재조회)."""
    fin = ref["financials"]
    stocks = ref["stocks"]
    combos = [
        ("005930", "2025", "11011", "cumulative", "영업이익"),
        ("005930", "2025", "11011", "cumulative", "매출액"),
        ("005930", "2025", "11014", "cumulative", "영업이익"),
        ("005930", "2025", "11014", "quarter", "영업이익"),
        ("005930", "2025", "11012", "cumulative", "당기순이익"),
        ("005930", "2024", "11011", "cumulative", "매출액"),
        ("005930", "2025", "11011", "point_in_time", "자산총계"),
        ("000660", "2025", "11011", "cumulative", "영업이익"),
        ("000660", "2025", "11011", "cumulative", "매출액"),
        ("000660", "2025", "11014", "quarter", "영업이익"),
        ("000660", "2025", "11013", "cumulative", "당기순이익"),
        ("000660", "2024", "11011", "cumulative", "영업이익"),
        ("000660", "2025", "11011", "point_in_time", "부채총계"),
        ("005380", "2025", "11011", "cumulative", "매출액"),
        ("005380", "2025", "11011", "cumulative", "영업이익"),
        ("005380", "2025", "11014", "cumulative", "당기순이익"),
        ("005380", "2024", "11011", "cumulative", "매출액"),
        ("034020", "2025", "11011", "cumulative", "영업이익"),
        ("034020", "2025", "11011", "cumulative", "매출액"),
        ("034020", "2025", "11014", "quarter", "영업이익"),
        ("042660", "2025", "11011", "cumulative", "영업이익"),
        ("042660", "2025", "11011", "cumulative", "매출액"),
        ("042660", "2025", "11014", "cumulative", "당기순이익"),
        ("042660", "2024", "11011", "cumulative", "영업이익"),
        ("005930", "2025", "11013", "cumulative", "매출액"),
    ]
    templates = [
        "{name} {year}년 {period} {amount} {acct}은 얼마야?",
        "{name}({code}) {year}년 {period} {acct} 알려줘",
        "{year}년 {name} {period} {acct} 얼마나 나왔어?",
    ]
    cases = []
    for i, (code, year, reprt, amount, acct) in enumerate(combos):
        row = _fin_lookup(fin, code, year, reprt, amount, acct)
        name = stocks.get(code, code)
        period = REPRT_LABEL[reprt]
        amount_label = AMOUNT_LABEL[amount]
        # point_in_time 은 "누적/단독" 표현이 어색해 문구에서 뺀다.
        amt_text = "" if amount == "point_in_time" else amount_label
        q = templates[i % len(templates)].format(
            name=name, code=code, year=year, period=period, amount=amt_text, acct=acct
        )
        q = " ".join(q.split())
        confirmed = row is not None
        cases.append(
            EvalCase(
                id=f"fin-{i + 1:02d}",
                type="정확한 재무 숫자",
                question=q,
                stock_code=code,
                required_tools=["get_financial_facts"],
                forbidden_tools=["search_research_reports", "get_stock_prices"],
                expected_args={
                    "get_financial_facts": {
                        "stock_code": code,
                        "account_name": acct,
                        "business_year": year,
                    }
                },
                expected_financial={
                    "stock_code": code,
                    "account_name": acct,
                    "business_year": year,
                    "report_period": PERIOD_KEY[reprt],
                    "amount_type": amount,
                    "fs_div": "CFS",
                    "value_kind": "actual",
                },
                expected_period={
                    "business_year": year,
                    "report_period": period,
                    "amount_type": amt_text or None,
                },
                gold_sources=[
                    {
                        # 실제 source_key 형식(app/services/facts.py): amount_type 은
                        # 한글 라벨이 아니라 DB 원값(cumulative/quarter/point_in_time).
                        "source_type": "financial",
                        "source_id": f"{code}/{year}/{reprt}/CFS/{acct}/{amount}",
                        "ref": f"{name} {year} {period} {acct}",
                    }
                ],
                allowed_source_types=["financial"],
                forbidden_claims=["전망", "예상치"],
                review_status="confirmed" if confirmed else "needs_manual_review",
                label_basis=(
                    f"financials 실제 행(thstrm_amount={row['thstrm_amount']})" if row else ""
                ),
            )
        )
    return cases


def _topic_of(title: str, name: str) -> str:
    """사건 제목에서 질문에 쓸 짧은 주제어를 뽑는다.

    투자자가 실제로 칠 법한 짧은 표현이어야 하므로 제목 앞부분의 명사 덩어리를 쓴다.
    종목명은 질문에 이미 있으므로 뺀다.
    """
    # 제목이 "현대차, 엔비디아와 로봇 …" 처럼 종목명 + 쉼표로 시작하는 경우가 많다.
    # 앞 조각이 종목명뿐이면 다음 조각에서 주제어를 뽑는다.
    parts = [p.strip() for p in re.split(r"[,…·—:]", title) if p.strip()]
    for part in parts:
        stripped = part.replace(name, "").strip(" '\"-")
        words = [w for w in stripped.split() if w]
        if words:
            return " ".join(words[:3]).strip(" ,'\"")
    return ""


def build_news(ref: dict) -> list[EvalCase]:
    """뉴스 사건·영향 25문항. 정답 = news_clusters 실제 사건."""
    stocks = ref["stocks"]
    clusters = ref["clusters"]
    # 질문이 서로 겹치지 않게 실제 사건의 핵심어를 넣는다(같은 종목에 여러 문항이
    # 배정되므로 종목명만으로는 문자열이 중복된다).
    templates = [
        "{name} {topic} 관련해서 무슨 일 있었어?",
        "{name} {topic} 뉴스 어떻게 된 거야?",
        "{name} {topic} 이슈 설명해줘",
        "{name} {topic} 관련 소식 알려줘",
        "{name} {topic} 건은 어떤 내용이야?",
    ]
    cases = []
    # 종목을 고르게 섞는다(한 종목에 몰리지 않게).
    by_stock: dict[str, list[dict]] = {}
    for c in clusters:
        by_stock.setdefault(c["stock_code"], []).append(c)
    # 주제어를 못 뽑는 사건은 질문이 "OO  관련 소식"처럼 어색해지므로 건너뛴다.
    # 같은 종목에서 주제어가 겹치면 질문 문자열이 중복되므로 앞의 것만 남긴다.
    for code in by_stock:
        kept: list[dict] = []
        seen_topics: set[str] = set()
        for c in by_stock[code]:
            topic = _topic_of(c.get("summary_title") or "", stocks.get(code, code))
            if not topic or topic in seen_topics:
                continue
            seen_topics.add(topic)
            kept.append(c)
        by_stock[code] = kept
    picked: list[dict] = []
    idx = 0
    while len(picked) < 25 and any(len(v) > idx for v in by_stock.values()):
        for code in sorted(by_stock):
            if len(picked) >= 25:
                break
            if len(by_stock[code]) > idx:
                picked.append(by_stock[code][idx])
        idx += 1

    for i, cl in enumerate(picked[:25]):
        code = cl["stock_code"]
        name = stocks.get(code, code)
        date = str(cl.get("first_published_at", ""))[:10]
        topic = _topic_of(cl.get("summary_title") or "", name)
        cases.append(
            EvalCase(
                id=f"news-{i + 1:02d}",
                type="뉴스 사건·영향",
                question=templates[i % len(templates)].format(name=name, topic=topic),
                stock_code=code,
                required_tools=["search_news"],
                forbidden_tools=["get_financial_facts"],
                optional_tools=["get_stock_prices"],
                expected_args={"search_news": {"stock_code": code}},
                gold_sources=[
                    {
                        "source_type": "news_event",
                        "ref": (cl.get("summary_title") or "")[:80],
                        "note": f"news_clusters.id={cl['id']} ({date}, {cl['sentiment_label']})",
                    }
                ],
                allowed_source_types=["news_event"],
                review_status="needs_manual_review",
                label_basis=(
                    f"news_clusters.id={cl['id']} 실재(기사 {cl['article_count']}건, {date}). "
                    "출처 chunk_id 는 검색 경로에 따라 달라져 식별자 미확정."
                ),
            )
        )
    return cases


def build_disclosures(ref: dict) -> list[EvalCase]:
    """공시 설명·구조화 값 20문항. 정답 = structured_disclosures 실제 접수번호."""
    stocks = ref["stocks"]
    disc = ref["disclosures"]
    # 종목을 번갈아 뽑아 한 종목에 몰리지 않게 한다(조합 27개 중 20개 사용).
    by_stock: dict[str, list[dict]] = {}
    for d in disc:
        by_stock.setdefault(d["stock_code"], []).append(d)
    picked: list[dict] = []
    idx = 0
    while len(picked) < 20 and any(len(v) > idx for v in by_stock.values()):
        for code in sorted(by_stock):
            if len(picked) >= 20:
                break
            if len(by_stock[code]) > idx:
                picked.append(by_stock[code][idx])
        idx += 1

    # 같은 공시 유형이 여러 종목에 걸쳐 나오므로 표현을 돌려 쓴다(말투 단조로움 방지).
    type_q = {
        "dividend_matter": [
            "{name} 배당 얼마나 줬어?",
            "{name} 배당금 얼마야?",
            "{name} 주당 배당금 알려줘",
            "{name} 작년에 배당 얼마 나왔어?",
            "{name} 배당 내역 정리해줘",
        ],
        "treasury_stock_status": [
            "{name} 자기주식 얼마나 보유하고 있어?",
            "{name} 자사주 보유량 알려줘",
            "{name} 자기주식 현황 어때?",
            "{name} 자사주 얼마나 갖고 있어?",
            "{name} 보유 자기주식 수량 알려줘",
        ],
        "treasury_stock_acquisition": [
            "{name} 자사주 매입한 거 있어?",
            "{name} 자기주식 취득 공시 알려줘",
        ],
        "treasury_stock_disposal": [
            "{name} 자사주 처분한 내역 알려줘",
            "{name} 자기주식 처분 공시 있어?",
        ],
        "stock_total_status": [
            "{name} 총 발행주식수 알려줘",
            "{name} 주식 몇 주 발행돼 있어?",
            "{name} 발행주식 총수 얼마야?",
            "{name} 상장주식수 알려줘",
            "{name} 총 주식수 얼마나 돼?",
        ],
        "capital_change_status": [
            "{name} 자본금 변동 내역 있어?",
            "{name} 증자·감자 이력 알려줘",
        ],
        "paid_in_capital_increase": ["{name} 유상증자 공시 내용 알려줘"],
        "overseas_listing": ["{name} 해외상장 관련 공시 있어?"],
        "overseas_listing_decision": ["{name} 해외상장 결정 공시 내용 알려줘"],
    }
    used_per_type: dict[str, int] = {}
    cases = []
    for d in picked:
        code = d["stock_code"]
        name = stocks.get(code, code)
        et = d["event_type"]
        variants = type_q.get(et) or ["{name} " + et + " 공시 알려줘"]
        k = used_per_type.get(et, 0)
        used_per_type[et] = k + 1
        q = variants[k % len(variants)].format(name=name)
        cases.append(
            EvalCase(
                id=f"disc-{len(cases) + 1:02d}",
                type="공시 설명·구조화 값",
                question=q,
                stock_code=code,
                required_tools_any=["get_disclosure_values", "search_disclosures"],
                forbidden_tools=["search_research_reports"],
                expected_args={"get_disclosure_values": {"stock_code": code}},
                gold_sources=[
                    {
                        "source_type": "structured_disclosure",
                        "source_id": d.get("rcept_no"),
                        "ref": f"{name} {et}",
                        "note": f"announced_at={str(d.get('announced_at', ''))[:10]}",
                    }
                ],
                allowed_source_types=["structured_disclosure", "dart_document"],
                forbidden_claims=["증권사", "목표주가"],
                review_status="confirmed" if d.get("rcept_no") else "needs_manual_review",
                label_basis=(
                    f"structured_disclosures 실제 행 rcept_no={d.get('rcept_no')}, event_type={et}"
                ),
            )
        )
    return cases


def build_reports(ref: dict) -> list[EvalCase]:
    """증권사 리포트 20문항. 정답 = research_reports 실제 리포트(목표주가 stated)."""
    stocks = ref["stocks"]
    reports = ref["reports"]
    by_stock: dict[str, list[dict]] = {}
    for r in reports:
        by_stock.setdefault(r["stock_code"], []).append(r)
    picked: list[dict] = []
    idx = 0
    while len(picked) < 20 and any(len(v) > idx for v in by_stock.values()):
        for code in sorted(by_stock):
            if len(picked) >= 20:
                break
            if len(by_stock[code]) > idx:
                picked.append(by_stock[code][idx])
        idx += 1

    # 같은 종목에 여러 문항이 배정되므로 증권사명을 넣어 질문을 구분한다.
    templates = [
        "{broker}에서 {name} 목표주가 얼마로 봤어?",
        "{broker} {name} 리포트 전망 어때?",
        "{date}에 나온 {broker} {name} 투자의견 알려줘",
        "{name}에 대한 {broker} 리포트 내용 요약해줘",
    ]
    cases = []
    for i, rp in enumerate(picked[:20]):
        code = rp["stock_code"]
        name = stocks.get(code, code)
        tp = rp.get("target_price")
        question = templates[i % len(templates)].format(
            name=name, broker=rp["broker"], date=str(rp["report_date"])[:10]
        )
        # 같은 증권사가 같은 종목에 여러 리포트를 낸 경우 문구가 겹친다 → 발행일로 구분.
        if question in {c.question for c in cases}:
            question = f"{str(rp['report_date'])[:10]}자 {question}"
        cases.append(
            EvalCase(
                id=f"report-{i + 1:02d}",
                type="증권사 리포트",
                question=question,
                stock_code=code,
                required_tools=["search_research_reports"],
                forbidden_tools=["get_financial_facts"],
                expected_args={"search_research_reports": {"stock_code": code}},
                gold_sources=[
                    {
                        "source_type": "research_report",
                        "ref": f"{rp['broker']} {rp['report_date']} {rp['title'][:40]}",
                        "page": rp.get("target_price_source_page"),
                        "note": f"research_reports.id={rp['id']}, target_price={tp}",
                    }
                ],
                allowed_source_types=["research_report"],
                forbidden_claims=["확정", "보장"],
                review_status="needs_manual_review",
                label_basis=(
                    f"research_reports 실재: {rp['broker']} {rp['report_date']} "
                    f"목표주가 {tp}(stated), 의견 {rp.get('investment_opinion')}. "
                    "질문이 특정 리포트를 지정하지 않아 정답 chunk 식별자 미확정."
                ),
            )
        )
    return cases


def build_mixed(ref: dict) -> list[EvalCase]:
    """복수 기능 혼합 20문항."""
    stocks = ref["stocks"]
    codes = ["005930", "000660", "005380", "034020", "042660"]
    # 종목(5) × 문형(4) = 20. 종목마다 문형을 조금씩 달리 써 말투가 반복되지 않게 한다.
    specs = [
        (
            [
                "{name} 실적이랑 최근 뉴스 같이 알려줘",
                "{name} 실적 어떻고 요즘 뉴스는 뭐 있어?",
                "{name} 재무 상황이랑 최근 소식 정리해줘",
                "{name} 실적하고 뉴스 한번에 보여줘",
                "{name} 요즘 실적이랑 이슈 같이 알려줘",
            ],
            ["get_financial_facts", "search_news"],
        ),
        (
            [
                "{name} 영업이익이 왜 줄었고 증권사 전망은 어때?",
                "{name} 실적 부진 이유랑 증권가 시각 알려줘",
                "{name} 최근 실적 이슈랑 애널리스트 의견 정리해줘",
                "{name} 왜 이런 실적이 나왔고 전망은 어떤지 알려줘",
                "{name} 실적 배경이랑 증권사 평가 같이 알려줘",
            ],
            ["search_news", "search_research_reports"],
        ),
        (
            [
                "{name} 목표주가랑 지금 주가 비교해줘",
                "{name} 현재가가 목표주가 대비 어느 정도야?",
                "{name} 증권사 목표가랑 실제 주가 차이 알려줘",
                "{name} 지금 주가랑 목표주가 얼마나 벌어져 있어?",
                "{name} 목표주가 대비 현재 주가 수준 알려줘",
            ],
            ["search_research_reports", "get_stock_prices"],
        ),
        (
            [
                "{name} 배당이랑 실적 같이 정리해줘",
                "{name} 배당 얼마 주고 실적은 어때?",
                "{name} 배당 내역이랑 재무 실적 알려줘",
                "{name} 배당하고 영업이익 같이 보여줘",
                "{name} 배당 정책이랑 실적 상황 정리해줘",
            ],
            ["get_disclosure_values", "get_financial_facts"],
        ),
    ]
    cases = []
    for i in range(20):
        code = codes[i % len(codes)]
        name = stocks.get(code, code)
        # 종목(5) × 문형(4) = 20 조합이 모두 달라지도록 인덱스를 분리한다.
        variants, tools = specs[i // len(codes)]
        cases.append(
            EvalCase(
                id=f"mix-{i + 1:02d}",
                type="복수 기능 혼합",
                question=variants[i % len(codes)].format(name=name),
                stock_code=code,
                required_tools=tools,
                optional_tools=[
                    t
                    for t in (
                        "search_news",
                        "get_financial_facts",
                        "search_research_reports",
                        "get_stock_prices",
                        "get_disclosure_values",
                    )
                    if t not in tools
                ],
                expected_args={tools[0]: {"stock_code": code}},
                allowed_source_types=[
                    "financial",
                    "news_event",
                    "research_report",
                    "price",
                    "structured_disclosure",
                ],
                review_status="needs_manual_review",
                label_basis=(
                    "복합 질문 — 필수 기능 2개 호출 여부로 채점. "
                    "정답 문서 식별자는 하위 질문마다 달라 미확정."
                ),
            )
        )
    return cases


def build_exclusion(ref: dict) -> list[EvalCase]:
    """부정·제외·대조 15문항."""
    stocks = ref["stocks"]
    codes = ["005930", "000660", "005380", "034020", "042660"]
    # 종목(5) × 문형(3) = 15. 제외 조건 표현을 여러 형태로 쓴다.
    specs = [
        (
            [
                "최근 뉴스에서 {name} 호재 있어? 실적 관련은 제외해.",
                "{name} 좋은 소식 있어? 실적 얘기는 빼고.",
                "실적 관련 내용 말고 {name} 최근 호재만 알려줘",
                "{name} 뉴스 알려주는데 실적 기사는 제외해줘",
                "{name} 최근 이슈 중에 실적 빼고 뭐 있어?",
            ],
            ["search_news"],
            ["get_financial_facts"],
            ["실적"],
        ),
        (
            [
                "{name} 증권사 전망 말고 회사가 직접 공시한 내용만 알려줘",
                "{name} 애널리스트 의견 빼고 공시만 보여줘",
                "증권사 리포트 말고 {name} 공식 공시 내용 알려줘",
                "{name} 회사가 직접 발표한 것만 알려줘, 증권사 건 빼고",
                "{name} 공시 자료만 알려줘. 증권사 전망은 필요 없어",
            ],
            ["search_disclosures"],
            ["search_research_reports"],
            ["증권사", "목표주가"],
        ),
        (
            [
                "{name} 목표주가 말고 실제 주가 알려줘",
                "{name} 지금 실제 주가만 알려줘, 목표주가 말고",
                "증권사 목표가 빼고 {name} 현재 주가 알려줘",
                "{name} 실제 거래되는 가격 알려줘. 목표주가는 빼고",
                "{name} 현재가만 알려줘, 목표주가는 필요 없어",
            ],
            ["get_stock_prices"],
            ["search_research_reports"],
            ["목표주가"],
        ),
    ]
    cases = []
    for i in range(15):
        code = codes[i % len(codes)]
        name = stocks.get(code, code)
        # 종목(5) × 문형(3) = 15 조합이 모두 달라지도록 인덱스를 분리한다.
        variants, req, forb, claims = specs[i // len(codes)]
        tmpl = variants[i % len(codes)]
        cases.append(
            EvalCase(
                id=f"excl-{i + 1:02d}",
                type="부정·제외·대조",
                question=tmpl.format(name=name),
                stock_code=code,
                required_tools=req,
                forbidden_tools=forb,
                expected_args={req[0]: {"stock_code": code}},
                forbidden_claims=claims,
                review_status="confirmed",
                label_basis=(
                    "제외 조건은 질문 자체로 확정 — 금지 기능 호출·금지 주제 포함 여부로 채점"
                ),
            )
        )
    return cases


def build_screen_context(ref: dict) -> list[EvalCase]:
    """현재 화면 문맥 10문항. 질문에 종목명이 없고 화면 문맥으로만 종목이 정해진다."""
    stocks = ref["stocks"]
    clusters = ref["clusters"]
    # 앞 5개(종목 선택 화면)와 뒤 5개(뉴스 상세 화면)는 문구를 다르게 둔다.
    # 공통점은 '질문에 종목명이 없다'는 것 — 문맥으로만 종목이 정해진다.
    stock_screen_qs = [
        ("어제 주가 어떻게 됐어?", ["get_stock_prices"]),
        ("이 회사 최근 실적 알려줘", ["get_financial_facts"]),
        ("지금 주가 얼마야?", ["get_stock_prices"]),
        ("이 종목 목표주가 얼마야?", ["search_research_reports"]),
        ("최근 뉴스 뭐 있어?", ["search_news"]),
    ]
    news_screen_qs = [
        ("이 뉴스 나온 회사 주가 지금 얼마야?", ["get_stock_prices"]),
        ("이 회사 영업이익 알려줘", ["get_financial_facts"]),
        ("이 회사에 대한 증권사 의견 있어?", ["search_research_reports"]),
        ("이 회사 다른 뉴스도 있어?", ["search_news"]),
        ("이 회사 배당 준 적 있어?", ["get_disclosure_values"]),
    ]
    cases = []
    for i in range(10):
        # 앞 5개는 종목만 선택된 화면, 뒤 5개는 특정 뉴스를 보고 있는 화면.
        if i < 5:
            code = ["005930", "000660", "005380", "034020", "042660"][i]
            ctx = {"stock_code": code}
            basis = f"화면에서 {stocks.get(code, code)}({code}) 선택 상태 — 질문에 종목명 없음"
            q, req = stock_screen_qs[i]
        else:
            cl = clusters[(i - 5) % len(clusters)]
            code = cl["stock_code"]
            ctx = {
                "stock_code": code,
                "context_source_type": "news_event",
                "context_source_id": str(cl["id"]),
            }
            basis = (
                f"{stocks.get(code, code)} 뉴스(news_clusters.id={cl['id']}) 상세 화면 — "
                "질문에 종목명 없음"
            )
            q, req = news_screen_qs[i - 5]
        cases.append(
            EvalCase(
                id=f"ctx-{i + 1:02d}",
                type="현재 화면 문맥",
                question=q,
                context=ctx,
                required_tools=req,
                expected_args={req[0]: {"stock_code": code}},
                expected_facts=[stocks.get(code, code)],
                review_status="confirmed",
                label_basis=basis + " → 문맥 종목으로 인식해 되묻지 않아야 함",
            )
        )
    return cases


def build_unanswerable(ref: dict) -> list[EvalCase]:
    """답변 불가능·모호 10문항."""
    specs = [
        (
            "삼성전자 내년 매출 확정값 알려줘",
            "005930",
            "확정된 미래 실적은 없다고 밝혀야 한다. 전망치를 확정값처럼 말하면 실패.",
            ["확정", "확실"],
        ),
        (
            "999999 종목 주가 알려줘",
            None,
            "지원하지 않는 종목이라고 밝혀야 한다. 다른 종목으로 대체하면 실패.",
            [],
        ),
        (
            "주가 알려줘",
            None,
            "어떤 종목인지 되물어야 한다. 임의 종목을 골라 답하면 실패.",
            [],
        ),
        (
            "삼성전자 2030년 영업이익 얼마야?",
            "005930",
            "해당 연도 데이터가 없다고 밝혀야 한다. 다른 연도로 대체하면 실패.",
            [],
        ),
        (
            "이 종목 사도 돼?",
            "005930",
            "투자 판단은 제공하지 않는다고 밝혀야 한다.",
            ["추천", "사세요", "매수하세요"],
        ),
        (
            "삼성전자 CEO 개인 연봉 얼마야?",
            "005930",
            "보유 데이터에 없다고 밝혀야 한다.",
            [],
        ),
        (
            "그 뉴스 이후 주가 어떻게 됐어?",
            "005930",
            "어떤 뉴스인지 특정되지 않으면 되물어야 한다. "
            "임의 사건을 고르거나 일반 기간 수익률로 대체하면 실패.",
            [],
        ),
        (
            "한화오션 2026년 3분기 배당금 얼마야?",
            "042660",
            "미래 기간 데이터가 없다고 밝혀야 한다.",
            [],
        ),
        (
            "삼성전자랑 애플 실적 비교해줘",
            "005930",
            "애플은 보유 종목이 아니라고 밝혀야 한다. 애플 숫자를 만들어내면 실패.",
            [],
        ),
        (
            "내일 주가 오를까?",
            "000660",
            "미래 주가는 예측하지 않는다고 밝혀야 한다.",
            ["오릅니다", "확실히", "보장"],
        ),
    ]
    cases = []
    for i, (q, code, expect, claims) in enumerate(specs):
        cases.append(
            EvalCase(
                id=f"na-{i + 1:02d}",
                type="답변 불가능·모호",
                question=q,
                stock_code=code,
                is_answerable=False,
                no_data_expectation=expect,
                forbidden_claims=claims,
                review_status="confirmed",
                label_basis="답변 불가 사유가 질문 자체로 확정(미래값·미보유 종목·문맥 부족)",
            )
        )
    return cases


def split_dev_holdout(cases: list[EvalCase]) -> tuple[list[EvalCase], list[EvalCase]]:
    """유형별 비율을 유지하며 개발 120 / 홀드아웃 40 으로 나눈다(§6).

    무작위가 아니라 유형별 뒤에서 25% 를 홀드아웃으로 떼어 재현 가능하게 한다.
    """
    by_type: dict[str, list[EvalCase]] = {}
    for c in cases:
        by_type.setdefault(c.type, []).append(c)

    target_hold = round(len(cases) * HOLDOUT_RATIO)
    # 유형별 홀드아웃 수를 먼저 내림으로 정하고, 총합이 목표에 못 미치면
    # 소수부가 큰 유형부터 1개씩 더 준다(총 40개를 정확히 맞추기 위해).
    exact = {t: len(g) * HOLDOUT_RATIO for t, g in by_type.items()}
    n_hold = {t: int(v) for t, v in exact.items()}
    short = target_hold - sum(n_hold.values())
    for t in sorted(exact, key=lambda k: exact[k] - int(exact[k]), reverse=True)[: max(0, short)]:
        n_hold[t] += 1

    dev: list[EvalCase] = []
    hold: list[EvalCase] = []
    for t in TYPE_QUOTA:
        group = by_type.get(t, [])
        cut = len(group) - n_hold.get(t, 0)
        for c in group[:cut]:
            c.split = "dev"
            dev.append(c)
        for c in group[cut:]:
            c.split = "holdout"
            c.id = f"h-{c.id}"
            hold.append(c)
    return dev, hold


def main() -> int:
    client = get_supabase_client()
    ref = load_reference(client)
    print(
        f"기준 데이터: 종목 {len(ref['stocks'])} / 재무행 {len(ref['financials'])} / "
        f"리포트 {len(ref['reports'])} / 클러스터 {len(ref['clusters'])} / "
        f"공시 {len(ref['disclosures'])} / 용어 {len(ref['terms'])}"
    )

    cases: list[EvalCase] = []
    cases += build_terms(ref)
    cases += build_financials(ref)
    cases += build_news(ref)
    cases += build_disclosures(ref)
    cases += build_reports(ref)
    cases += build_mixed(ref)
    cases += build_exclusion(ref)
    cases += build_screen_context(ref)
    cases += build_unanswerable(ref)

    counts: dict[str, int] = {}
    for c in cases:
        counts[c.type] = counts.get(c.type, 0) + 1
    print(f"생성 {len(cases)}문항: {json.dumps(counts, ensure_ascii=False)}")
    for t, want in TYPE_QUOTA.items():
        got = counts.get(t, 0)
        if got != want:
            print(f"  경고: {t} {got}/{want}")

    dev, hold = split_dev_holdout(cases)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for name, group in (("devset.json", dev), ("holdout.json", hold)):
        suite = EvalSuite(
            note=(
                "Phase 8 평가셋. 정답 라벨은 실제 DB(financials·research_reports·"
                "structured_disclosures·news_clusters·rag_terms)에서 생성했다. "
                "RAG 생성 답변을 정답으로 쓰지 않는다. "
                "review_status=needs_manual_review 는 원본 근거 미확정 라벨이다."
            ),
            cases=group,
        )
        (OUT_DIR / name).write_text(
            json.dumps(suite.model_dump(mode="json"), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        need = sum(1 for c in group if c.review_status == "needs_manual_review")
        print(f"{name}: {len(group)}문항 (수동 검토 필요 {need})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
