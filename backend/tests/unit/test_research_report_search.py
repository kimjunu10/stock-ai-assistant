"""ResearchReportSearch 단위 테스트(외부 호출 mock).

하이브리드 검색 재사용·메타 보강·partial 방어 제외·broker 필터를 검증한다.
"""

from __future__ import annotations

from app.core.config import Settings
from app.rag.retrieval import RetrievedChunk
from app.services.research_reports import ResearchReportSearch


class _FakeRetriever:
    def __init__(self, chunks):
        self._chunks = chunks
        self.calls = []

    def search(self, question, **kwargs):
        self.calls.append(kwargs)
        return self._chunks


class _FakeTable:
    def __init__(self, db, name):
        self._db = db
        self._name = name
        self._filter_vals = None

    def select(self, *a, **k):
        return self

    def in_(self, col, vals):
        self._filter_vals = vals
        return self

    def execute(self):
        return type("R", (), {"data": self._db.data.get(self._name, [])})()


class _FakeDB:
    def __init__(self, data):
        self.data = data

    def table(self, name):
        return _FakeTable(self, name)


def _chunk(cid, file_hash, page, stock="005930"):
    return RetrievedChunk(
        chunk_id=cid,
        document_id="d" + cid,
        content=f"본문{cid}",
        value_kind=None,
        stock_code=stock,
        source_type="research_report",
        published_at="2026-05-04",
        source_pk=file_hash,
        title="doc제목",
        publisher=None,
        source_url=None,
        similarity=0.8,
        source_locator={"report_id": "r1" if file_hash == "h1" else "r2", "page_number": page},
    )


def _svc(chunks, db_data):
    cfg = Settings()
    return ResearchReportSearch(_FakeDB(db_data), cfg, _FakeRetriever(chunks))


def _db(reports, pages, tables):
    return {
        "research_reports": reports,
        "research_report_pages": pages,
        "research_report_tables": tables,
    }


def test_reuses_hybrid_with_report_source_type():
    svc = _svc([_chunk("1", "h1", 2)], _db([], [], []))
    svc.search("삼성전자 목표주가", stock_code="005930")
    assert svc._retriever.calls[0]["source_type"] == "research_report"
    assert svc._retriever.calls[0]["stock_code"] == "005930"


def test_enriches_report_meta_and_page():
    reports = [
        {
            "id": "r1",
            "file_hash": "h1",
            "stock_code": "005930",
            "title": "메모리 천하",
            "broker": "IBK투자증권",
            "report_date": "2026-05-04",
            "investment_opinion": "매수",
            "parse_status": "success",
        }
    ]
    pages = [{"report_id": "r1", "page_number": 2, "elements": {"pdf_page": 1, "source_page": 2}}]
    tables = [{"report_id": "r1", "page_number": 2, "value_kind": "forecast"}]
    svc = _svc([_chunk("1", "h1", 2)], _db(reports, pages, tables))
    hits = svc.search("전망", stock_code="005930")
    assert len(hits) == 1
    h = hits[0]
    assert h.broker == "IBK투자증권"
    assert h.report_date == "2026-05-04"
    assert h.page_number == 2 and h.pdf_page == 1 and h.source_page == 2
    assert h.table_value_kinds == {"forecast": 1}  # 전망값 노출


def test_partial_report_excluded_defensively():
    reports = [
        {
            "id": "r1",
            "file_hash": "h1",
            "stock_code": "005930",
            "title": "스캔",
            "broker": "미래에셋증권",
            "report_date": "2026-05-18",
            "investment_opinion": None,
            "parse_status": "partial",
        }
    ]
    svc = _svc([_chunk("1", "h1", 1)], _db(reports, [], []))
    assert svc.search("아무거나", stock_code="005930") == []


def test_broker_filter():
    reports = [
        {
            "id": "r1",
            "file_hash": "h1",
            "stock_code": "005930",
            "title": "A",
            "broker": "IBK투자증권",
            "report_date": "2026-05-04",
            "investment_opinion": "매수",
            "parse_status": "success",
        },
        {
            "id": "r2",
            "file_hash": "h2",
            "stock_code": "005930",
            "title": "B",
            "broker": "키움증권",
            "report_date": "2026-03-03",
            "investment_opinion": "매수",
            "parse_status": "success",
        },
    ]
    svc = _svc([_chunk("1", "h1", 1), _chunk("2", "h2", 1)], _db(reports, [], []))
    hits = svc.search("목표주가", stock_code="005930", broker="키움")
    assert len(hits) == 1 and hits[0].broker == "키움증권"
