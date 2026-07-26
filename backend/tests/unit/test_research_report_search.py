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
        self._rows = list(db.data.get(name, []))

    def select(self, *a, **k):
        return self

    def in_(self, col, vals):
        vals = set(vals)
        self._rows = [r for r in self._rows if r.get(col) in vals]
        return self

    def eq(self, col, val):
        self._rows = [r for r in self._rows if r.get(col) == val]
        return self

    def gte(self, col, val):
        self._rows = [r for r in self._rows if (r.get(col) or "") >= val]
        return self

    def lte(self, col, val):
        self._rows = [r for r in self._rows if (r.get(col) or "") <= val]
        return self

    def order(self, col, desc=False):
        self._rows = sorted(self._rows, key=lambda r: r.get(col) or "", reverse=bool(desc))
        return self

    def limit(self, n):
        self._rows = self._rows[:n]
        return self

    def execute(self):
        return type("R", (), {"data": self._rows})()


class _FakeDB:
    def __init__(self, data):
        self.data = data

    def table(self, name):
        return _FakeTable(self, name)


def _chunk(cid, file_hash, page, stock="005930", report_id=None):
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
        source_locator={
            "report_id": report_id or ("r1" if file_hash == "h1" else "r2"),
            "page_number": page,
        },
    )


def _svc(chunks, db_data):
    cfg = Settings()
    return ResearchReportSearch(_FakeDB(db_data), cfg, _FakeRetriever(chunks))


def _db(reports, pages, tables, documents=None, chunks=None):
    return {
        "research_reports": reports,
        "research_report_pages": pages,
        "research_report_tables": tables,
        "rag_documents": documents or [],
        "rag_chunks": chunks or [],
    }


def _doc(doc_id, file_hash):
    return {
        "id": doc_id,
        "source_pk": file_hash,
        "is_current": True,
        "source_type": "research_report",
    }


def _rag_chunk(chunk_id, doc_id, page_number, content="본문"):
    return {
        "id": chunk_id,
        "document_id": doc_id,
        "content": content,
        "source_locator": {"page_number": page_number},
        "is_active": True,
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
    """broker 가 있으면 벡터 검색을 거치지 않고 메타에서 그 증권사만 직접 가져온다.

    종목 전체 후보의 상위 top_k 안에 그 증권사 청크가 없어 최신 리포트를 놓치던
    결함(report-09) 방지 — broker 필터는 이제 검색 후처리가 아니라 선행 조회다.
    """
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
    documents = [_doc("d1", "h1"), _doc("d2", "h2")]
    chunks = [_rag_chunk("c1", "d1", 1), _rag_chunk("c2", "d2", 1)]
    svc = _svc([], _db(reports, [], [], documents, chunks))
    hits = svc.search("목표주가", stock_code="005930", broker="키움")
    assert len(hits) == 1 and hits[0].broker == "키움증권"


def _report(rid, fh, broker, rdate, *, tp=None, tp_status="unknown", eff=None, stock="005930"):
    return {
        "id": rid,
        "file_hash": fh,
        "stock_code": stock,
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


# ── promptv2 회귀 테스트 ──


def test_default_time_context_is_current():
    """§1: time_context 미지정이어도 current 정책(증권사별 최신 1건)이 적용된다."""
    reports = [
        _report("r1", "h1", "미래에셋증권", "2026-05-04", tp=320000, tp_status="stated"),
        _report("r2", "h2", "미래에셋증권", "2026-04-02", tp=300000, tp_status="stated"),
        _report("r3", "h3", "하나증권", "2026-05-01", tp=480000, tp_status="stated"),
    ]
    chunks = [
        _chunk("1", "h1", 1, report_id="r1"),
        _chunk("2", "h2", 1, report_id="r2"),
        _chunk("3", "h3", 1, report_id="r3"),
    ]
    svc = _svc(chunks, _db(reports, [], []))
    # time_context 를 넘기지 않는다 → 그래도 미래에셋은 최신 1건만 나와야 한다.
    hits = svc.search("삼성전자 최근 목표주가", stock_code="005930")
    brokers = [h.broker for h in hits]
    assert brokers.count("미래에셋증권") == 1
    mirae = next(h for h in hits if h.broker == "미래에셋증권")
    assert mirae.report_date == "2026-05-04"  # 최신


def test_other_stock_target_price_dropped():
    """§2: 요청 종목(005930)과 다른 종목 리포트의 target_price 는 절대 반환하지 않는다."""
    reports = [
        _report("r1", "h1", "하나증권", "2026-05-04", tp=480000, tp_status="stated"),
        # SK하이닉스(000660) 리포트가 유사검색으로 섞여 들어옴 → 그 목표주가는 배제.
        _report(
            "r2", "h2", "한화투자증권", "2026-05-04", tp=330000, tp_status="stated", stock="000660"
        ),
    ]
    chunks = [
        _chunk("1", "h1", 1, stock="005930", report_id="r1"),
        _chunk("2", "h2", 1, stock="000660", report_id="r2"),
    ]
    svc = _svc(chunks, _db(reports, [], []))
    hits = svc.search("삼성전자 목표주가", stock_code="005930")
    # 다른 종목 리포트는 목표주가가 강등되어 stated 가 아니고 값이 없다.
    other = [h for h in hits if h.broker == "한화투자증권"]
    if other:  # 검색결과에 남더라도
        assert other[0].target_price is None
        assert other[0].target_price_status == "ambiguous"
    # 어떤 hit 도 330000(타 종목 값)을 stated 로 반환하지 않는다.
    assert all(not (h.target_price == 330000 and h.target_price_status == "stated") for h in hits)


def test_history_value_excluded_from_current():
    """§3: effective_date 가 report_date 와 다른 과거 이력값은 current 에서 배제."""
    reports = [
        # report_date=2026-05-04 인데 effective_date=2025-04-09 → 이력표 과거값.
        _report(
            "r1",
            "h1",
            "한화투자증권",
            "2026-05-04",
            tp=73000,
            tp_status="stated",
            eff="2025-04-09",
        ),
    ]
    svc = _svc([_chunk("1", "h1", 1, report_id="r1")], _db(reports, [], []))
    hits = svc.search("삼성전자 목표주가", stock_code="005930", time_context="current")
    h = next(h for h in hits if h.broker == "한화투자증권")
    assert h.target_price is None  # 과거 이력값은 current 에서 강등
    assert h.target_price_status == "ambiguous"


def test_history_context_keeps_per_date_values():
    """§3: time_context=history 는 날짜별 개별값을 그대로 유지(범위 합성/강등 없음)."""
    reports = [
        _report(
            "r1", "h1", "한화투자증권", "2026-05-04", tp=73000, tp_status="stated", eff="2025-04-09"
        ),
        _report(
            "r2", "h2", "한화투자증권", "2026-06-04", tp=84000, tp_status="stated", eff="2025-08-01"
        ),
    ]
    chunks = [_chunk("1", "h1", 1, report_id="r1"), _chunk("2", "h2", 1, report_id="r2")]
    svc = _svc(chunks, _db(reports, [], []))
    hits = svc.search("삼성전자 목표주가 변화", stock_code="005930", time_context="history")
    tps = sorted(h.target_price for h in hits if h.target_price is not None)
    # history 에서는 개별 이력값이 강등되지 않고 그대로 남는다.
    assert tps == [73000, 84000]


def test_current_dedupes_identical_broker_date_tp():
    """§4: 같은 증권사·발행일·목표주가 완전중복은 제거된다."""
    reports = [
        _report("r1", "h1", "하나증권", "2025-12-17", tp=155000, tp_status="stated"),
        _report("r2", "h2", "하나증권", "2025-12-17", tp=155000, tp_status="stated"),  # 완전중복
    ]
    chunks = [_chunk("1", "h1", 1, report_id="r1"), _chunk("2", "h2", 1, report_id="r2")]
    svc = _svc(chunks, _db(reports, [], []))
    hits = svc.search(
        "삼성전자 목표주가", stock_code="005930", time_context="current", as_of_date="2025-12-18"
    )
    hana = [h for h in hits if h.broker == "하나증권"]
    assert len(hana) == 1  # 중복 제거 + 증권사별 최신 1건


def test_empty_query_lists_recent_without_embedding():
    """검색 주제 없는 '최근 리포트 목록' 요청은 임베딩(retriever.search)을 부르지 않는다.

    search_research_reports 가 query="" 로 호출되면 임베딩 계층이 빈 문자열
    입력을 거부해 오류가 나던 운영 결함(round3 A케이스) 회귀 방지.
    """
    reports = [
        _report("r1", "h1", "미래에셋증권", "2026-07-08", tp=550000, tp_status="stated"),
        _report("r2", "h2", "키움증권", "2026-07-08", tp=390000, tp_status="stated"),
    ]
    documents = [_doc("d1", "h1"), _doc("d2", "h2")]
    chunks = [_rag_chunk("c1", "d1", 1), _rag_chunk("c2", "d2", 1)]
    svc = _svc([], _db(reports, [], [], documents, chunks))
    hits = svc.search("", stock_code="005930", time_context="current")
    assert svc._retriever.calls == []  # 임베딩 검색 미호출
    assert {h.broker for h in hits} == {"미래에셋증권", "키움증권"}


def test_broker_filter_finds_report_outside_vector_topk():
    """broker 지정 시 그 증권사 최신 리포트를 항상 찾는다(벡터 후보 밖이어도).

    report-09 회귀: 종목 리포트가 많아 벡터 검색 top_k 안에 특정 증권사의
    최신 리포트가 없으면 오래된 리포트를 잘못 반환하던 결함.
    """
    reports = [_report("r1", "h1", "SK증권", "2026-07-13", tp=134000, tp_status="stated")]
    reports += [
        _report(f"r{i}", f"h{i}", "타증권", f"2026-07-{i:02d}", tp=100000 + i, tp_status="stated")
        for i in range(2, 12)
    ]
    documents = [_doc(f"d{i}", f"h{i}") for i in range(1, 12)]
    chunks = [_rag_chunk(f"c{i}", f"d{i}", 1) for i in range(1, 12)]
    svc = _svc([], _db(reports, [], [], documents, chunks))
    # 벡터 검색 후보에 SK증권 청크가 전혀 없어도(리트리버가 빈 결과를 주더라도)
    # broker 조회는 벡터 검색을 거치지 않으므로 영향받지 않는다.
    hits = svc.search("목표주가", stock_code="005930", broker="SK증권", time_context="current")
    assert len(hits) == 1
    assert hits[0].broker == "SK증권" and hits[0].target_price == 134000


def test_report_id_lookup_returns_specific_report():
    """document_id 문맥으로 확정된 특정 리포트를 report_id 로 직접 조회한다."""
    reports = [_report("r1", "h1", "하나증권", "2026-07-08", tp=480000, tp_status="stated")]
    documents = [_doc("d1", "h1")]
    chunks = [_rag_chunk("c1", "d1", 1, content="목표주가 근거 본문")]
    svc = _svc([], _db(reports, [], [], documents, chunks))
    hits = svc.get_by_report_id("r1", stock_code="005930")
    assert len(hits) == 1
    assert hits[0].broker == "하나증권" and hits[0].target_price == 480000


def test_report_id_lookup_stock_mismatch_drops_target_price():
    """report_id 로 조회했는데 문맥 종목과 리포트 종목이 다르면 목표주가를 신뢰하지 않는다."""
    reports = [_report("r1", "h1", "하나증권", "2026-07-08", tp=480000, tp_status="stated")]
    documents = [_doc("d1", "h1")]
    chunks = [_rag_chunk("c1", "d1", 1)]
    svc = _svc([], _db(reports, [], [], documents, chunks))
    hits = svc.get_by_report_id("r1", stock_code="000660")  # 리포트는 005930 소속
    assert len(hits) == 1
    assert hits[0].target_price is None
    assert hits[0].target_price_status == "ambiguous"
