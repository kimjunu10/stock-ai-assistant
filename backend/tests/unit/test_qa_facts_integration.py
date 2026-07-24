"""FactsQaService 를 QA API 단일 진입점으로 통합한 뒤의 회귀/라우팅 테스트.

외부 호출(HybridRetriever.search, FactsService SQL, Solar 생성)은 전부 mock 으로
무해화한다. QueryPlan 판정에 따라 실제 실행 경로가 갈리는지, 순수 뉴스 질문이
기존 경로와 동일하게 동작하는지, 응답 스키마가 유지되는지 검증한다.
"""

from __future__ import annotations

from app.core.config import Settings
from app.rag.retrieval import RetrievedChunk
from app.schemas.qa import QaResponse
from app.services.facts import NumericFact
from app.services.rag_qa_facts import FactsQaService


class _FakeRetriever:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def search(self, question, **kwargs):
        self.calls.append({"question": question, **kwargs})
        return [
            RetrievedChunk(
                chunk_id="c1",
                document_id="d1",
                content="삼성전자 뉴스 본문",
                value_kind="news_interpretation",
                stock_code="005930",
                source_type="news_event",
                published_at="2026-07-22",
                source_pk="1",
                title="뉴스 제목",
                publisher="언론사",
                source_url="http://x",
                similarity=0.9,
            )
        ]


class _FakeFacts:
    def __init__(self) -> None:
        self.financials_calls = 0
        self.term_calls = 0

    def get_financials(self, stock_code, **kwargs):
        self.financials_calls += 1
        return [
            NumericFact(
                label="영업이익",
                value=6_000_000_000_000,
                unit="원",
                period="2025년 연간 누적",
                basis="연결",
                value_kind="actual_value",
                source_type="financials",
                source_key="005930/2025/11014/CFS/영업이익/cumulative",
            )
        ]

    def lookup_term(self, term_query):
        self.term_calls += 1
        return {"term": "PER", "official_definition": "주가수익비율", "english_name": None}


class _FakeGenerator:
    def __init__(self) -> None:
        self.prompts: list[str] = []

    def generate(self, system, user):
        self.prompts.append(user)
        return "답변 [1]"

    def stream(self, system, user):
        self.prompts.append(user)
        yield "답변 "
        yield "[1]"


def _service():
    retr, facts, gen = _FakeRetriever(), _FakeFacts(), _FakeGenerator()
    svc = FactsQaService(retr, facts, gen, Settings())
    return svc, retr, facts, gen


def test_pure_news_question_uses_only_retriever():
    """순수 뉴스 질문: 검색만 호출하고 SQL/용어는 호출하지 않는다(기존 경로 회귀 방지)."""
    svc, retr, facts, gen = _service()
    result = svc.answer("삼성전자 최근 뉴스 알려줘.", stock_code="005930")
    assert len(retr.calls) == 1
    assert facts.financials_calls == 0
    assert facts.term_calls == 0
    assert result.sources and result.numeric_sources == []
    assert result.term is None


def test_numeric_question_uses_sql():
    svc, retr, facts, gen = _service()
    result = svc.answer("삼성전자 2025년 영업이익은 얼마야?", stock_code="005930")
    assert facts.financials_calls == 1
    # 숫자 출처가 단위·기간·value_kind·출처키를 보존
    assert result.numeric_sources[0]["unit"] == "원"
    assert result.numeric_sources[0]["value_kind"] == "actual_value"
    assert result.numeric_sources[0]["period"].startswith("2025")
    assert result.numeric_sources[0]["source_key"]
    # 실제 숫자가 프롬프트에 그대로 전달됨(LLM 이 재계산하지 않도록)
    assert "6,000,000,000,000" in gen.prompts[0] or "6000000000000" in gen.prompts[0]


def test_pure_numeric_question_does_not_call_retriever():
    """순수 숫자 질문: 뉴스 검색(HybridRetriever.search) 을 호출하지 않는다.

    임베딩 API 호출을 유발하지 않도록 문서 검색 경로가 완전히 꺼져야 한다.
    """
    svc, retr, facts, gen = _service()
    result = svc.answer("삼성전자 2025년 영업이익 얼마?", stock_code="005930")
    assert facts.financials_calls == 1
    assert retr.calls == []  # 검색 미호출
    assert result.sources == []  # 문서 출처 없음
    assert result.numeric_sources  # 숫자 출처만 존재


def test_pure_term_question_does_not_call_retriever():
    svc, retr, facts, gen = _service()
    svc.answer("PER이 뭐야?")
    assert facts.term_calls == 1
    assert retr.calls == []  # 용어만; 검색 미호출


def test_term_question_uses_lookup():
    svc, retr, facts, gen = _service()
    result = svc.answer("PER이 뭐야?")
    assert facts.term_calls == 1
    assert result.term and result.term["term"] == "PER"


def test_mixed_question_combines_sql_and_news():
    svc, retr, facts, gen = _service()
    result = svc.answer("삼성전자 영업이익은 얼마고 왜 변했어?", stock_code="005930")
    assert facts.financials_calls == 1
    assert len(retr.calls) == 1  # 뉴스 검색도 수행
    assert result.numeric_sources and result.sources


def test_missing_stock_code_yields_no_numeric():
    """혼합 질문이지만 종목코드가 없으면 SQL 은 빈 결과로 안전 처리."""
    svc, retr, facts, gen = _service()
    result = svc.answer("영업이익은 얼마고 왜 변했어?")  # stock_code 없음
    # get_financials 는 stock_code 없으면 _fetch_numeric 에서 조기 반환
    assert facts.financials_calls == 0
    assert result.numeric_sources == []


def test_response_schema_regression():
    """QaResponse 가 기존 필드 + 신규 선택 필드로 구성돼 검증을 통과한다."""
    svc, retr, facts, gen = _service()
    r = svc.answer("삼성전자 2025년 영업이익은 얼마야?", stock_code="005930")
    resp = QaResponse(
        answer=r.answer,
        sources=r.sources,
        numeric_sources=r.numeric_sources,
        term=r.term,
        invalid_citations=r.invalid_citations,
        latency_ms=r.latency_ms,
    )
    assert resp.answer == "답변 [1]"
    assert resp.numeric_sources[0].unit == "원"


def test_stream_returns_sources_and_tokens():
    svc, retr, facts, gen = _service()
    sources, numeric_sources, term, token_iter = svc.stream(
        "삼성전자 2025년 영업이익은 얼마야?", stock_code="005930"
    )
    assert numeric_sources and numeric_sources[0]["unit"] == "원"
    assert "".join(token_iter) == "답변 [1]"
