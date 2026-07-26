"""뉴스 검색 종료일 경계 회귀 테스트 (Phase 8 2차 교정).

운영 결함: relative_period="recent" 는 "오늘까지 포함"인 날짜 범위를 주는데,
날짜만 있는 종료일(YYYY-MM-DD)이 timestamptz 로 그 날 00:00 으로 해석돼
당일 뉴스가 통째로 검색에서 빠졌다(뉴스 청크는 대부분 실제 발행 시각을 가짐).
"오늘 뉴스 알려줘"가 오늘 것을 하나도 못 찾는 형태로 드러났다.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.agent.time_context import resolve_relative_date_range
from app.core.config import Settings
from app.rag.retrieval import HybridRetriever, _inclusive_end


class _NoEmbed:
    def embed_query(self, _q: str) -> list[float]:
        return [0.0] * 8


class _CaptureDB:
    """rpc 인자만 잡아두는 최소 스텁."""

    def __init__(self) -> None:
        self.params: dict = {}

    def rpc(self, _name: str, params: dict):
        self.params = params
        return self

    def execute(self):
        return type("R", (), {"data": []})()


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("2026-07-26", "2026-07-26T23:59:59+09:00"),  # 날짜만 → 그 날 끝까지
        ("2026-07-26T10:00:00+09:00", "2026-07-26T10:00:00+09:00"),  # 시각 지정은 그대로
        (None, None),
    ],
)
def test_inclusive_end_extends_date_only_bound(raw, expected):
    assert _inclusive_end(raw) == expected


def test_hybrid_search_sends_inclusive_end_to_rpc():
    """하이브리드 검색이 종료일을 그 날 끝까지로 넓혀 RPC 에 넘긴다."""
    db = _CaptureDB()
    r = HybridRetriever(db, Settings(), _NoEmbed())
    r.search(
        "갤럭시",
        stock_code="005930",
        source_type="news_event",
        date_from="2026-07-24",
        date_to="2026-07-26",
        expand_parent=False,
    )
    assert db.params["filter_to"] == "2026-07-26T23:59:59+09:00"
    assert db.params["filter_from"] == "2026-07-24"  # 시작일은 건드리지 않는다


def test_recent_range_end_covers_same_day_news():
    """recent 의 종료일이 당일 오후 발행 뉴스를 포함한다(회귀 방지)."""
    _, end = resolve_relative_date_range("recent", reference_date=date(2026, 7, 26))
    assert end == "2026-07-26"
    # 보정 전에는 당일 09:13 뉴스가 잘렸다.
    assert _inclusive_end(end) > "2026-07-26T09:13:00+09:00"
