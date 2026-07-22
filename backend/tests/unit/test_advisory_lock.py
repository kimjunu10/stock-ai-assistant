"""advisory_lock 유틸 단위 테스트 (psycopg 는 monkeypatch)."""

from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock

from app.db.advisory_lock import advisory_lock


def test_no_database_url_yields_false():
    with advisory_lock("", 123) as acquired:
        assert acquired is False


def _install_fake_psycopg(monkeypatch, *, try_lock_result: bool):
    """psycopg.connect 를 가짜로 심는다. 반환된 커서/연결 mock 을 함께 돌려준다."""
    cur = MagicMock()
    cur.fetchone.return_value = (try_lock_result,)
    cur.__enter__ = lambda s: cur
    cur.__exit__ = lambda s, *a: False

    conn = MagicMock()
    conn.cursor.return_value = cur

    fake = types.ModuleType("psycopg")
    fake.connect = MagicMock(return_value=conn)
    monkeypatch.setitem(sys.modules, "psycopg", fake)
    return conn, cur


def test_acquires_and_unlocks(monkeypatch):
    conn, cur = _install_fake_psycopg(monkeypatch, try_lock_result=True)
    with advisory_lock("postgres://x", 999) as acquired:
        assert acquired is True
    # 획득했으면 잠금 시도 + 해제 + close 가 호출된다
    sqls = [c.args[0] for c in cur.execute.call_args_list]
    assert any("pg_try_advisory_lock" in s for s in sqls)
    assert any("pg_advisory_unlock" in s for s in sqls)
    conn.close.assert_called_once()


def test_busy_does_not_unlock(monkeypatch):
    conn, cur = _install_fake_psycopg(monkeypatch, try_lock_result=False)
    with advisory_lock("postgres://x", 999) as acquired:
        assert acquired is False
    sqls = [c.args[0] for c in cur.execute.call_args_list]
    assert any("pg_try_advisory_lock" in s for s in sqls)
    # 획득 못 했으면 unlock 하지 않는다(다른 보유자의 락을 풀면 안 됨)
    assert not any("pg_advisory_unlock" in s for s in sqls)
    conn.close.assert_called_once()


def test_connection_error_yields_false(monkeypatch):
    fake = types.ModuleType("psycopg")
    fake.connect = MagicMock(side_effect=OSError("connection refused"))
    monkeypatch.setitem(sys.modules, "psycopg", fake)
    with advisory_lock("postgres://x", 999) as acquired:
        assert acquired is False
