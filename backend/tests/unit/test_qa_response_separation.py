"""공식 정보 / 증권사 의견 API 분리 테스트 (prompt.md §8)."""

from __future__ import annotations

from app.api.routes.qa import _broker_opinions, _official_information
from app.schemas.qa import NumericSource


def test_broker_opinion_target_price_only_when_stated():
    reports = [
        {
            "broker": "하나증권",
            "report_date": "2026-05-04",
            "title": "갈 길이 멀다",
            "investment_opinion": "BUY",
            "chunk_id": "rc1",
            "source_page": 1,
            "target_price": 480000,
            "target_price_currency": "KRW",
            "target_price_status": "stated",
        },
        {
            "broker": "키움증권",
            "report_date": "2026-05-04",
            "title": "보유",
            "investment_opinion": "보유",
            "chunk_id": "rc2",
            "target_price": 999999,
            "target_price_status": "unknown",  # 미확정
        },
    ]
    ops = _broker_opinions(reports)
    assert ops[0].broker == "하나증권" and ops[0].target_price == 480000
    # 미확정 리포트는 목표주가 숫자를 노출하지 않는다
    assert ops[1].target_price is None and ops[1].target_price_status == "unknown"


def test_broker_opinions_empty_when_no_reports():
    assert _broker_opinions([]) == []


def test_official_information_from_numeric_sources():
    ns = [
        NumericSource(
            label="영업이익",
            value=43_601_051_000_000,
            unit="원",
            period="2025 사업보고서(연간) 누적",
            basis="연결",
            value_kind="actual_value",
            source_type="financials",
            source_key="005930/2025/11011",
        )
    ]
    info = _official_information(ns)
    assert info[0]["label"] == "영업이익" and info[0]["value"] == 43_601_051_000_000
    assert info[0]["basis"] == "연결"


def test_official_information_empty():
    assert _official_information([]) == []
