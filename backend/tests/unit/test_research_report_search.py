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


def _report(rid, fh, broker, rdate, *, tp=None, tp_status="unknown", eff=None):
    return {
        "id": rid,
        "file_hash": fh,
        "stock_code": "005930",
        "title": f"{broker} 리포트",
        "broker": broker,
        "report_date": rdate,
        "investment_opinion": "매수",
        "parse_status": "success",
        "target_price": tp,
        "target_price_currency": "KRW",
        "target_price_status": tp_status,
        "target_price_effective_date": eff,
        "target_price_source_page": 1 if tp else None,
    }


def test_enrich_exposes_structured_target_price():
    reports = [
        _report(
            "r1", "h1", "하나증권", "2026-05-04", tp=480000, tp_status="stated", eff="2026-05-04"
        )
    ]
    svc = _svc([_chunk("1", "h1", 2)], _db(reports, [], []))
    h = svc.search("목표주가", stock_code="005930")[0]
    assert h.target_price == 480000 and h.target_price_status == "stated"
    assert h.target_price_effective_date == "2026-05-04"


def test_current_policy_latest_per_broker_no_bias():
    # 같은 증권사(미래에셋) 3건 + 다른 증권사 1건 → 미래에셋은 최신 1건만, 편중 방지
    reports = [
        _report("r1", "h1", "미래에셋증권", "2026-05-04", tp=320000, tp_status="stated"),
        _report("r2", "h2", "미래에셋증권", "2026-04-02", tp=300000, tp_status="stated"),
        _report("r3", "h3", "미래에셋증권", "2026-01-30", tp=247000, tp_status="stated"),
        _report("r4", "h4", "하나증권", "2026-05-01", tp=480000, tp_status="stated"),
    ]
    chunks = [
        _chunk("1", "h1", 1),
        _chunk("2", "h2", 1),
        _chunk("3", "h3", 1),
        _chunk("4", "h4", 1),
    ]
    svc = _svc(chunks, _db(reports, [], []))
    hits = svc.search(
        "목표주가", stock_code="005930", time_context="current", as_of_date="2026-05-05"
    )
    brokers = [h.broker for h in hits]
    assert brokers.count("미래에셋증권") == 1  # 증권사별 최신 1건
    assert set(brokers) == {"미래에셋증권", "하나증권"}
    mirae = next(h for h in hits if h.broker == "미래에셋증권")
    assert mirae.report_date == "2026-05-04" and mirae.target_price == 320000  # 최신 행


def test_current_policy_marks_stale_beyond_90d():
    reports = [
        _report("r1", "h1", "키움증권", "2026-05-04", tp=560000, tp_status="stated"),
        _report("r2", "h2", "대신증권", "2025-12-01", tp=155000, tp_status="stated"),
    ]
    svc = _svc([_chunk("1", "h1", 1), _chunk("2", "h2", 1)], _db(reports, [], []))
    hits = svc.search(
        "목표주가", stock_code="005930", time_context="current", as_of_date="2026-05-05"
    )
    stale = {h.broker: h.is_stale for h in hits}
    assert stale["키움증권"] is False  # 90일 이내
    assert stale["대신증권"] is True  # 90일 초과(오래된 자료)
