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

import pytest
from pydantic import ValidationError

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


# ── news: exclude 경고 노출 ──
class _FakeRetriever:
    def search(self, q, **kwargs):
        from app.rag.retrieval import RetrievedChunk

        return [
            RetrievedChunk(
                chunk_id="c1",
                document_id="d1",
                content="공급계약 뉴스",
                value_kind=None,
                stock_code="005930",
                source_type="news_event",
                published_at="2026-07-01",
                source_pk="1",
                title="공급계약",
                publisher="언론사",
                source_url="http://x",
                similarity=0.9,
            )
        ]


def test_search_news_surfaces_exclude_topics():
    r = run_search_news(
        _FakeRetriever(),
        SearchNewsInput(stock_code="005930", query="호재", exclude_topics=["실적", "영업이익"]),
    )
    assert r.status == "ok"
    assert any("제외" in w for w in r.warnings)
    assert r.data["applied_filters"]["exclude_topics"] == ["실적", "영업이익"]


# ── reports: source metadata + forecast 경고 ──
class _FakeReports:
    def search(self, q, **kwargs):
        return [
            ReportHit(
                chunk_id="rc1",
                content="목표주가 상향",
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
