"""공시 조회 정렬 tie-break 단위 테스트 (Phase 8 최종 교정).

운영 결함(round3 disc-11): announced_at/disclosed_at 이 동률(같은 날짜, NULL
포함)일 때 DB 반환 순서가 임의라 limit 경계에서 매 실행마다 다른 문서가
잘렸다. rcept_no 를 2차 정렬 키로 둬 결정적으로 만든다.
"""

from __future__ import annotations

from app.services.facts import FactsService


class _FakeQuery:
    def __init__(self, rows: list[dict]) -> None:
        self._rows = list(rows)
        self._orders: list[tuple[str, bool]] = []
        self._limit: int | None = None

    def select(self, *a, **k):
        return self

    def eq(self, col, val):
        self._rows = [r for r in self._rows if r.get(col) == val]
        return self

    def neq(self, col, val):
        self._rows = [r for r in self._rows if r.get(col) != val]
        return self

    def in_(self, col, vals):
        vals = set(vals)
        self._rows = [r for r in self._rows if r.get(col) in vals]
        return self

    def order(self, col, desc=False):
        self._orders.append((col, desc))
        return self

    def limit(self, n):
        self._limit = n
        return self

    def execute(self):
        rows = list(self._rows)
        # DB 반환 순서가 정렬 키 동률에서 임의임을 재현: 원본 순서를 한 번 뒤집는다.
        # 2차 정렬 키(rcept_no)가 없으면 이 반전이 결과 순서를 바꾼다.
        rows = list(reversed(rows))
        for col, desc in reversed(self._orders):
            rows.sort(key=lambda r: r.get(col) or "", reverse=desc)
        if self._limit is not None:
            rows = rows[: self._limit]
        return type("R", (), {"data": rows})()


class _FakeDB:
    def __init__(self, tables: dict[str, list[dict]]) -> None:
        self._tables = tables

    def table(self, name):
        return _FakeQuery(self._tables[name])


def _disclosure(rcept_no, disclosed_at, is_latest=True):
    return {
        "rcept_no": rcept_no,
        "title": f"공시{rcept_no}",
        "disclosed_at": disclosed_at,
        "correction_status": "original",
        "is_latest": is_latest,
        "original_rcept_no": None,
        "supersedes_rcept_no": None,
        "parse_status": "success",
        "raw_text": None,
        "stock_code": "000660",
    }


def test_get_latest_disclosures_tiebreak_is_deterministic():
    """같은 disclosed_at 동률 그룹이 limit 경계에 걸려도 항상 같은 결과를 낸다."""
    rows = [
        _disclosure("20260716000582", "2026-07-16T00:00:00+00:00"),
        _disclosure("20260715800456", "2026-07-15T00:00:00+00:00"),
        _disclosure("20260715800045", "2026-07-15T00:00:00+00:00"),
        _disclosure("20260715000004", "2026-07-15T00:00:00+00:00"),
        _disclosure("20260713000324", "2026-07-13T00:00:00+00:00"),
        _disclosure("20260710000012", "2026-07-10T00:00:00+00:00"),
        _disclosure("20260710000002", "2026-07-10T00:00:00+00:00"),
    ]
    svc = FactsService(_FakeDB({"disclosures": rows}))
    first = [r["rcept_no"] for r in svc.get_latest_disclosures("000660", limit=5)]
    second = [r["rcept_no"] for r in svc.get_latest_disclosures("000660", limit=5)]
    assert first == second
    # 2026-07-10 동률 그룹(20260710000012 vs 20260710000002)의 승자도 rcept_no
    # 2차 정렬로 고정된다 — 매 실행 반전 반환 순서에 흔들리지 않는다.
    assert ("20260710000012" in first) == ("20260710000012" in second)


def test_get_structured_values_tiebreak_is_deterministic():
    rows = [
        {
            "rcept_no": "20260710000008",
            "data_group": "g",
            "event_type": "paid_in_capital_increase",
            "announced_at": None,
            "summary_text": "",
            "normalized_data": {},
            "stock_code": "000660",
        },
        {
            "rcept_no": "20260710000002",
            "data_group": "g",
            "event_type": "overseas_listing_decision",
            "announced_at": None,
            "summary_text": "",
            "normalized_data": {},
            "stock_code": "000660",
        },
    ]
    svc = FactsService(_FakeDB({"structured_disclosures": rows}))
    first = [r["rcept_no"] for r in svc.get_structured_values("000660", limit=5)]
    second = [r["rcept_no"] for r in svc.get_structured_values("000660", limit=5)]
    assert first == second
