"""뉴스 색인 정리 스크립트의 안전 계약 테스트 (Phase 8 2차 교정).

이 스크립트는 운영 데이터를 바꾸므로, 무엇을 하지 '않는지'를 고정한다.
  - 원본(news_clusters)·문서(rag_documents)를 삭제하지 않는다.
  - 청크를 hard delete 하지 않는다(is_active=false 로만 내린다).
  - 현행 문서(is_current=true)의 청크는 건드리지 않는다.
  - dry-run 이 기본이며, --apply 없이는 쓰기가 없다.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_PATH = Path(__file__).resolve().parents[2] / "scripts" / "cleanup_stale_news_chunks.py"
_spec = importlib.util.spec_from_file_location("cleanup_stale_news_chunks", _PATH)
cleanup = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cleanup)


class _Query:
    def __init__(self, table: _Table, op: str | None = None) -> None:
        self._t = table
        self._op = op
        self._filters: dict = {}

    def select(self, *_a, **kw):
        self._op = "select"
        self._count = kw.get("count")
        return self

    def update(self, payload):
        self._t.db.updates.append((self._t.name, payload))
        self._op = "update"
        self._payload = payload
        return self

    def delete(self):  # 호출되면 즉시 실패시킨다.
        raise AssertionError("정리 스크립트는 삭제를 하면 안 된다")

    def eq(self, k, v):
        self._filters[k] = v
        return self

    def in_(self, k, vals):
        self._filters[k] = list(vals)
        return self

    def range(self, start, end):
        self._range = (start, end)
        return self

    def execute(self):
        if self._op == "update":
            ids = self._filters.get("id", [])
            for c in self._t.db.chunks:
                if c["id"] in ids:
                    c.update(self._payload)
            return type("R", (), {"data": [], "count": len(ids)})()

        if self._t.name == "rag_documents":
            rows = [
                {"id": d["id"]}
                for d in self._t.db.docs
                if d["source_type"] == self._filters.get("source_type", d["source_type"])
                and d["is_current"] == self._filters.get("is_current", d["is_current"])
            ]
        else:
            want = self._filters.get("document_id", [])
            rows = [
                {"id": c["id"]}
                for c in self._t.db.chunks
                if c["document_id"] in want
                and c["is_active"] == self._filters.get("is_active", c["is_active"])
            ]
        start, end = getattr(self, "_range", (0, len(rows) - 1))
        page = rows[start : end + 1]
        return type("R", (), {"data": page, "count": len(rows)})()


class _Table:
    def __init__(self, db, name):
        self.db = db
        self.name = name

    def __getattr__(self, item):
        return getattr(_Query(self), item)


class _FakeDB:
    def __init__(self, docs, chunks):
        self.docs = docs
        self.chunks = chunks
        self.updates: list = []

    def table(self, name):
        return _Table(self, name)


@pytest.fixture
def db():
    docs = [
        {"id": "d-old", "source_type": "news_event", "is_current": False},
        {"id": "d-new", "source_type": "news_event", "is_current": True},
    ]
    chunks = [
        {"id": "c-old", "document_id": "d-old", "is_active": True},
        {"id": "c-new", "document_id": "d-new", "is_active": True},
    ]
    return _FakeDB(docs, chunks)


def test_dry_run_makes_no_writes(db):
    n = cleanup._deactivate(db, apply=False)
    assert n == 1  # 비현행 활성 청크 1건이 대상
    assert db.updates == []  # 쓰기 없음
    assert db.chunks[0]["is_active"] is True  # 그대로


def test_apply_deactivates_only_stale_chunks(db):
    cleanup._deactivate(db, apply=True)
    by_id = {c["id"]: c for c in db.chunks}
    assert by_id["c-old"]["is_active"] is False  # 비현행 → 내림
    assert by_id["c-new"]["is_active"] is True  # 현행은 건드리지 않음
    # soft 처리만 한다(삭제 아님)
    assert all(payload == {"is_active": False} for _, payload in db.updates)


def test_second_run_is_idempotent(db):
    cleanup._deactivate(db, apply=True)
    db.updates.clear()
    assert cleanup._deactivate(db, apply=True) == 0  # 남은 대상 없음
    assert db.updates == []


def test_stats_counts_current_and_stale_separately(db):
    s = cleanup._stats(db)
    assert s == {
        "stale_documents": 1,
        "stale_active_chunks": 1,
        "current_documents": 1,
        "current_active_chunks": 1,
    }
