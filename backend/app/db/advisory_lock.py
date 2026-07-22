"""PostgreSQL advisory lock 기반 프로세스·인스턴스 간 상호배제.

여러 uvicorn 워커/컨테이너/인스턴스에서 스케줄러가 동시에 떠도
같은 advisory lock 키를 잡는 쪽만 임계구역에 들어간다.

- 세션 레벨 lock: 같은 커넥션에서 획득·해제해야 하므로 전용 psycopg 커넥션을 유지한다.
- non-blocking(pg_try_advisory_lock): 이미 잡혀 있으면 즉시 False.
- DATABASE_URL 이 없거나 연결 실패 시에는 lock 을 얻지 못한 것으로 보지 않고,
  호출부가 결정하도록 (acquired=False, reason) 을 반환한다.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator

logger = logging.getLogger("uvicorn.error.advisory_lock")

# 임의의 고정 64-bit 키. 뉴스 RAG 증분 인덱싱 전용.
NEWS_RAG_INDEX_LOCK_KEY = 0x5241_4749_4E44_5831  # "RAGINDX1"


@contextmanager
def advisory_lock(database_url: str, key: int) -> Iterator[bool]:
    """advisory lock 을 non-blocking 으로 시도한다.

    yield 값:
      True  -> lock 획득(임계구역 실행 가능). 블록 종료 시 자동 해제.
      False -> 다른 프로세스가 이미 보유 or DATABASE_URL 미설정/연결 실패.
    """

    if not database_url:
        logger.warning("ADVISORY_LOCK_NO_DATABASE_URL key=%s", hex(key))
        yield False
        return

    import psycopg  # 런타임 의존성. import 실패 시 예외를 그대로 노출.

    conn = None
    acquired = False
    try:
        conn = psycopg.connect(database_url, autocommit=True)
        with conn.cursor() as cur:
            cur.execute("select pg_try_advisory_lock(%s)", (key,))
            acquired = bool(cur.fetchone()[0])
        yield acquired
    except Exception:  # noqa: BLE001 - 잠금 인프라 실패를 호출부로 전파하지 않는다
        logger.exception("ADVISORY_LOCK_ERROR key=%s", hex(key))
        yield False
        return
    finally:
        if conn is not None:
            try:
                if acquired:
                    with conn.cursor() as cur:
                        cur.execute("select pg_advisory_unlock(%s)", (key,))
            except Exception:  # noqa: BLE001
                logger.exception("ADVISORY_UNLOCK_ERROR key=%s", hex(key))
            finally:
                conn.close()
