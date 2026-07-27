"""Phase 5.5-B Tool 계약 단위 테스트. 외부 호출은 fake 로 무해화(실제 DB·모델 없음).

검증(문서 5.5-B):
- 공통 ToolResult/SourceRef 계약, error sanitize, 결과 크기 제한
- get_financial_facts 기간·amount_type 엄격 검증 + 다른 기간 fallback 없음(no_data)
- report_period → DART reprt_code 올바른 매핑(11013=q1, 11011=annual)
- search_disclosures latest_only 기본값
- search_research_reports source metadata·partial 제외(검색 계층 위임)
- Agent 가 SQL 문자열을 전달할 수 없음(입력 스키마에 SQL 필드 부재)
"""

from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError

from app.agent.time_context import resolve_relative_date_range
from app.agent.tools.common import (
    ToolResult,
    clamp_items,
    clamp_text,
    error,
    no_data,
    sanitize_exception,
)
from app.agent.tools.disclosures import SearchDisclosuresInput, run_search_disclosures
from app.agent.tools.financials import (
    PERIOD_TO_REPRT,
    FinancialFactsInput,
    run_get_financial_facts,
)
from app.agent.tools.news import SearchNewsInput, run_search_news
from app.agent.tools.reports import SearchResearchReportsInput, run_search_research_reports
from app.agent.tools.terms import FinancialTermInput, run_lookup_financial_term
from app.services.facts import NumericFact
from app.services.research_reports import ReportHit


# ── 공통 계약 ──
def test_toolresult_status_and_serialization():
    r = no_data("없음")
    assert r.status == "no_data" and r.data == {} and "없음" in r.warnings
    dumped = r.model_dump_agent()
    assert dumped["status"] == "no_data"


def test_error_hides_internal_message():
    r = error("안전 메시지")
    assert r.status == "error" and r.warnings == ["안전 메시지"]


def test_sanitize_exception_no_stack():
    msg = sanitize_exception(ValueError("secret db dsn leak"))
    assert "secret" not in msg and "dsn" not in msg


def test_clamp_helpers():
    assert clamp_text("a" * 5000).endswith("…")
    assert len(clamp_items(list(range(50)), 12)) == 12


# ── DART 코드 매핑(공식) ──
def test_report_period_maps_to_official_reprt_code():
    assert PERIOD_TO_REPRT == {"q1": "11013", "half": "11012", "q3": "11014", "annual": "11011"}


# ── 입력 스키마: SQL 문자열 전달 불가 ──
def test_financial_input_has_no_sql_field():
    fields = set(FinancialFactsInput.model_fields)
    assert "sql" not in fields and "query" not in fields
    # 잘못된 종목코드 거부
    with pytest.raises(ValidationError):
        FinancialFactsInput(stock_code="abc", account_name="영업이익")
    # 허용 외 계정 거부
    with pytest.raises(ValidationError):
        FinancialFactsInput(stock_code="005930", account_name="EBITDA")


# ── get_financial_facts ──
class _FakeFacts:
    def __init__(self, rows=None):
        self._rows = rows or []
        self.last_kwargs = None

    def get_financials(self, stock_code, **kwargs):
        self.last_kwargs = kwargs
        return self._rows

    def lookup_term(self, term):
        return (
            {"term": "PER", "official_definition": "주가수익비율", "source_name": "한국은행"}
            if term == "PER"
            else None
        )

    def get_latest_disclosures(self, stock_code, **kwargs):
        self.last_kwargs = kwargs
        return [
            {
                "rcept_no": "R1",
                "title": "자기주식취득",
                "disclosed_at": "2026-05-01",
                "correction_status": "original",
                "is_latest": True,
            }
        ]

    def get_disclosure_by_id(self, rcept_no, *, stock_code):
        if rcept_no != "R7" or stock_code != "005930":
            return None
        return {
            "rcept_no": "R7",
            "title": "현재 화면 공시",
            "disclosed_at": "2026-06-01",
            "correction_status": "original",
            "is_latest": True,
        }

    def get_structured_values(self, stock_code, **kwargs):
        return [
            {
                "rcept_no": "R2",
                "event_type": "dividend_matter",
                "announced_at": "2026-03-01",
                "summary_text": "배당 500원",
                "normalized_data": {"amount": 500},
            }
        ]


def _fact(period="2025년 사업보고서(연간) 누적"):
    return NumericFact(
        label="영업이익",
        value=6_000_000_000_000,
        unit="원",
        period=period,
        basis="연결",
        value_kind="actual_value",
        source_type="financials",
        source_key="005930/2025/11011/CFS/영업이익/cumulative",
    )


def _dated_fact(year: str, reprt_code: str, amount_type: str, value: int):
    fact = _fact(f"{year}년 테스트 기간")
    fact.value = value
    fact.extra = {
        "bsns_year": year,
        "reprt_code": reprt_code,
        "amount_type": amount_type,
        "fs_div": "CFS",
    }
    return fact


def test_financial_annual_passes_correct_reprt_code():
    facts = _FakeFacts(rows=[_fact()])
    r = run_get_financial_facts(
        facts,
        FinancialFactsInput(
            stock_code="005930", account_name="영업이익", business_year=2025, report_period="annual"
        ),
    )
    assert r.status == "ok"
    assert facts.last_kwargs["reprt_code"] == "11011"  # annual
    assert facts.last_kwargs["amount_type"] == "cumulative"  # 손익 annual 기본
    assert r.sources[0].source_type == "financial"


def test_financial_no_data_does_not_fallback():
    facts = _FakeFacts(rows=[])  # 해당 기간 없음
    r = run_get_financial_facts(
        facts,
        FinancialFactsInput(
            stock_code="005930",
            account_name="영업이익",
            business_year=2099,
            report_period="q3",
            amount_type="quarter",
        ),
    )
    assert r.status == "no_data"
    assert "대체하지 않았습니다" in r.warnings[-1]


def test_financial_balance_defaults_point_in_time():
    facts = _FakeFacts(rows=[_fact("2025년 사업보고서(연간) 시점값")])
    run_get_financial_facts(
        facts,
        FinancialFactsInput(
            stock_code="005930", account_name="자산총계", business_year=2025, report_period="annual"
        ),
    )
    assert facts.last_kwargs["amount_type"] == "point_in_time"


def test_financial_latest_mode_returns_only_latest_official_period():
    facts = _FakeFacts(
        rows=[
            _dated_fact("2026", "11013", "cumulative", 133),
            _dated_fact("2025", "11014", "cumulative", 239),
            _dated_fact("2024", "11014", "cumulative", 225),
        ]
    )
    result = run_get_financial_facts(
        facts,
        FinancialFactsInput(stock_code="005930", account_name="매출액"),
    )
    assert result.status == "ok"
    assert [item["value_won"] for item in result.data["facts"]] == [133]
    assert result.data["selection"]["period_mode"] == "latest"
    assert result.data["selection"]["latest_available_period"] == "2026년 테스트 기간"


def test_financial_broad_request_uses_core_metrics_in_one_query():
    facts = _FakeFacts(rows=[])
    run_get_financial_facts(
        facts,
        FinancialFactsInput(stock_code="005930"),
    )
    assert facts.last_kwargs["account_names"] == ["매출액", "영업이익", "당기순이익"]


def test_relative_date_ranges_use_server_reference_date():
    reference = date(2026, 7, 25)
    assert resolve_relative_date_range("recent", reference_date=reference) == (
        "2026-07-23",
        "2026-07-25",
    )
    assert resolve_relative_date_range("yesterday", reference_date=reference) == (
        "2026-07-24",
        "2026-07-24",
    )
    assert resolve_relative_date_range("last_7_days", reference_date=reference) == (
        "2026-07-19",
        "2026-07-25",
    )


# ── term ──
def test_term_lookup_and_no_data():
    facts = _FakeFacts()
    assert run_lookup_financial_term(facts, FinancialTermInput(term="PER")).status == "ok"
    assert run_lookup_financial_term(facts, FinancialTermInput(term="없는용어")).status == "no_data"


# ── disclosures: latest_only 기본 ──
def test_search_disclosures_latest_only_default():
    assert SearchDisclosuresInput(stock_code="005930").latest_only is True
    facts = _FakeFacts()
    r = run_search_disclosures(facts, SearchDisclosuresInput(stock_code="005930"))
    assert r.status == "ok" and r.sources[0].source_type == "dart_document"


def test_search_disclosures_pins_exact_ui_selected_document():
    facts = _FakeFacts()
    r = run_search_disclosures(
        facts,
        SearchDisclosuresInput(
            stock_code="005930",
            current_document_id="R7",
        ),
    )
    assert r.status == "ok"
    assert r.data["disclosures"][0]["rcept_no"] == "R7"
    assert r.data["disclosures"][0]["title"] == "현재 화면 공시"


# ── news: 검색 주제 유무에 따른 경로 분리(prompt.md phase_7 빈 검색어 결함) ──
def _news_chunk(chunk_id, title, published_at, source_pk="1"):
    from app.rag.retrieval import RetrievedChunk

    return RetrievedChunk(
        chunk_id=chunk_id,
        document_id="d1",
        content=f"{title} 본문",
        value_kind=None,
        stock_code="005930",
        source_type="news_event",
        published_at=published_at,
        source_pk=source_pk,
        title=title,
        publisher="언론사",
        source_url="http://x",
        similarity=0.9,
    )


class _FakeRetriever:
    """검색 주제 있는 경로(search)와 없는 경로(list_recent_news)를 구분해 기록한다."""

    def __init__(self, recent=None):
        self.search_called = False
        self.search_kwargs = None
        self.recent_called = False
        self.recent_kwargs = None
        self._recent = recent

    def search(self, q, **kwargs):
        self.search_called = True
        self.search_kwargs = kwargs
        return [_news_chunk("c1", "공급계약", "2026-07-01")]

    def get_news_event(self, cluster_id, *, stock_code=None):
        if cluster_id != "77" or stock_code != "005930":
            return None
        return _news_chunk("news_cluster:77", "현재 화면 뉴스", "2026-07-26", "77")

    def list_recent_news(self, **kwargs):
        self.recent_called = True
        self.recent_kwargs = kwargs
        if self._recent is not None:
            return self._recent
        return [
            _news_chunk("news_cluster:2", "어제 사건 B", "2026-07-24T09:00:00+00:00", "2"),
            _news_chunk("news_cluster:1", "어제 사건 A", "2026-07-24T08:00:00+00:00", "1"),
        ]


def test_search_news_surfaces_exclude_topics():
    r = run_search_news(
        _FakeRetriever(),
        SearchNewsInput(stock_code="005930", query="호재", exclude_topics=["실적", "영업이익"]),
    )
    assert r.status == "ok"
    assert any("제외" in w for w in r.warnings)
    assert r.data["applied_filters"]["exclude_topics"] == ["실적", "영업이익"]
    assert r.data["news"][0]["source_id"] == "c1"
    assert r.data["news"][0]["url"] == "/news?cluster=1"
    assert r.sources[0].locator["original_url"] == "http://x"


def test_search_news_with_topic_uses_hybrid_search():
    """주제(HBM 등) 있으면 기존 하이브리드 search 경로."""
    fake = _FakeRetriever()
    r = run_search_news(
        fake, SearchNewsInput(stock_code="005930", query="HBM 공급계약", date_from="2026-07-24")
    )
    assert r.status == "ok"
    assert fake.search_called and not fake.recent_called
    assert r.data["applied_filters"]["mode"] == "hybrid_search"


def test_search_news_pins_exact_ui_selected_event_before_related_results():
    fake = _FakeRetriever()
    r = run_search_news(
        fake,
        SearchNewsInput(
            stock_code="005930",
            query="관련 이슈",
            current_event_id="77",
        ),
    )
    assert r.status == "ok"
    assert [item["title"] for item in r.data["news"][:2]] == [
        "현재 화면 뉴스",
        "공급계약",
    ]
    assert fake.search_kwargs["context_source_id"] == "77"


@pytest.mark.parametrize("empty_query", [None, "", "   "])
def test_search_news_without_topic_skips_embedding(empty_query):
    """None·빈·공백 query → list_recent_news(임베딩 없는 조건 조회) 경로."""
    fake = _FakeRetriever()
    r = run_search_news(
        fake,
        SearchNewsInput(
            stock_code="005930",
            query=empty_query,
            sentiment="negative",
            date_from="2026-07-24",
            date_to="2026-07-24",
        ),
    )
    assert r.status == "ok"
    assert fake.recent_called and not fake.search_called  # search(임베딩)는 호출 안 됨
    assert r.data["applied_filters"]["mode"] == "recent_events"
    assert r.data["applied_filters"]["sentiment"] == "negative"
    # 조건이 그대로 조회 계층에 전달됨(다른 종목·기간 대체 없음)
    assert fake.recent_kwargs["stock_code"] == "005930"
    assert fake.recent_kwargs["sentiment"] == "negative"


def test_search_news_no_topic_no_result_is_no_data_not_error():
    """결과 없으면 error 가 아니라 no_data(다른 종목·기간 대체 금지)."""
    fake = _FakeRetriever(recent=[])
    r = run_search_news(fake, SearchNewsInput(stock_code="005930", query=None))
    assert r.status == "no_data"
    assert fake.recent_called


# ── reports: source metadata + forecast 경고 ──
class _FakeReports:
    def __init__(self, tp=None, tp_status="unknown", is_stale=False):
        self._tp = tp
        self._tp_status = tp_status
        self._is_stale = is_stale
        self.last_kwargs = None

    def search(self, q, **kwargs):
        self.last_kwargs = kwargs
        return [
            ReportHit(
                chunk_id="rc1",
                content="목표주가 상향. 본문 숫자 999,999",
                stock_code="005930",
                report_id="r1",
                title="메모리 천하",
                broker="IBK투자증권",
                report_date="2026-05-04",
                investment_opinion="매수",
                page_number=2,
                pdf_page=1,
                source_page=2,
                table_value_kinds={"forecast": 3},
                similarity=0.8,
                target_price=self._tp,
                target_price_currency="KRW",
                target_price_status=self._tp_status,
                target_price_effective_date="2026-05-04" if self._tp else None,
                target_price_source_page=1 if self._tp else None,
                is_stale=self._is_stale,
            )
        ]


def test_search_reports_source_metadata_and_forecast_warning():
    r = run_search_research_reports(
        _FakeReports(), SearchResearchReportsInput(stock_code="005930", query="목표주가")
    )
    assert r.status == "ok"
    s = r.sources[0]
    assert s.source_type == "research_report" and s.page == 2 and s.publisher == "IBK투자증권"
    assert any("예측치" in w for w in r.warnings)
    assert r.data["reports"][0]["table_value_kinds"] == {"forecast": 3}


def test_reports_target_price_exposed_only_when_stated():
    # stated → target_price 노출
    r = run_search_research_reports(
        _FakeReports(tp=460000, tp_status="stated"),
        SearchResearchReportsInput(stock_code="005930", query="목표주가"),
    )
    item = r.data["reports"][0]
    assert item["target_price"] == 460000 and item["target_price_status"] == "stated"
    # snippet 숫자를 목표주가로 쓰지 말라는 경고가 존재
    assert any("snippet" in w for w in r.warnings)


def test_reports_target_price_hidden_when_not_stated():
    # unknown/not_stated/ambiguous → target_price 키 자체를 노출하지 않는다
    for st in ("unknown", "not_stated", "ambiguous", "parse_failed"):
        r = run_search_research_reports(
            _FakeReports(tp=999999, tp_status=st),
            SearchResearchReportsInput(stock_code="005930", query="목표주가"),
        )
        item = r.data["reports"][0]
        assert "target_price" not in item, f"{st} 인데 목표주가 노출됨"
        assert item["target_price_status"] == st


def test_reports_time_context_passed_through():
    fake = _FakeReports(tp=460000, tp_status="stated")
    run_search_research_reports(
        fake,
        SearchResearchReportsInput(
            stock_code="005930", query="최근 목표주가", time_context="current"
        ),
    )
    assert fake.last_kwargs["time_context"] == "current"


def test_reports_invalid_time_context_defaults_current():
    # promptv2 §1: 화이트리스트 밖(또는 미지정)이면 안전 기본값 current 로 처리한다.
    fake = _FakeReports()
    run_search_research_reports(
        fake,
        SearchResearchReportsInput(stock_code="005930", query="x", time_context="not_a_context"),
    )
    assert fake.last_kwargs["time_context"] == "current"


def test_reports_omitted_time_context_defaults_current():
    # promptv2 §1: Agent 가 time_context 를 생략해도 current 정책이 적용된다.
    fake = _FakeReports()
    run_search_research_reports(fake, SearchResearchReportsInput(stock_code="005930", query="x"))
    assert fake.last_kwargs["time_context"] == "current"


def test_all_tool_results_are_toolresult():
    facts = _FakeFacts(rows=[_fact()])
    outs = [
        run_lookup_financial_term(facts, FinancialTermInput(term="PER")),
        run_search_disclosures(facts, SearchDisclosuresInput(stock_code="005930")),
        run_search_news(_FakeRetriever(), SearchNewsInput(stock_code="005930", query="x")),
        run_search_research_reports(
            _FakeReports(), SearchResearchReportsInput(stock_code="005930", query="x")
        ),
    ]
    assert all(isinstance(o, ToolResult) for o in outs)
