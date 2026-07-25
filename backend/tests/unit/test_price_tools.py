"""주가 Tool 계층 단위 테스트 (Phase 6).

run_get_stock_prices / run_calculate_event_return 의 결과 계약·SourceRef·no_data·
숫자/단위/기간·일봉 요약을 검증한다(StockPriceService 를 가짜로 주입).
"""

from __future__ import annotations

from datetime import date, datetime

from app.agent.tools.prices import (
    CalculateEventReturnInput,
    GetStockPricesInput,
    run_calculate_event_return,
    run_get_stock_prices,
)
from app.services.stock_prices import DailyClose, PeriodReturn, PriceQuote


class FakeSvc:
    def __init__(self, quote=None, period=None, event=None, daily=None):
        self._quote = quote
        self._period = period
        self._event = event
        self._daily = daily or []

    def get_current_quote(self, stock_code):
        return self._quote

    def get_period_return(self, stock_code, *, start, end, adjusted=True):
        return self._period

    def get_event_return(self, stock_code, *, event_date, pre_days, post_days, adjusted=True):
        return self._event

    def get_daily_candles(self, stock_code, *, start, end, adjusted=True):
        return self._daily


def _quote():
    return PriceQuote(
        stock_code="005930",
        price=252500.0,
        previous_close=250000.0,
        change=2500.0,
        change_rate=1.0,
        currency="KRW",
        as_of=datetime.fromisoformat("2026-07-24T15:30:00+09:00"),
        trading_day=date(2026, 7, 24),
    )


def _period():
    return PeriodReturn(
        stock_code="005930",
        start_trading_day=date(2026, 6, 24),
        end_trading_day=date(2026, 7, 24),
        start_close=200000.0,
        end_close=250000.0,
        change=50000.0,
        return_pct=25.0,
        currency="KRW",
        adjusted=True,
    )


# ── 현재가 결과 계약 + SourceRef ───────────────────────────────────
def test_get_current_price_contract_and_source():
    r = run_get_stock_prices(FakeSvc(quote=_quote()), GetStockPricesInput(stock_code="005930"))
    assert r.status == "ok"
    q = r.data["quote"]
    assert q["price"] == 252500.0
    assert q["change_rate_pct"] == 1.0
    assert q["unit"] == "원"
    assert q["currency"] == "KRW"
    assert q["trading_day"] == "2026-07-24"
    assert len(r.sources) == 1
    s = r.sources[0]
    assert s.source_type == "price"
    assert s.publisher == "토스증권 Open API"
    assert s.published_at == "2026-07-24"
    assert s.value_kind == "actual"


# ── 기간 수익률(현재가 + lookback) ─────────────────────────────────
def test_get_prices_with_lookback_period():
    svc = FakeSvc(quote=_quote(), period=_period())
    r = run_get_stock_prices(svc, GetStockPricesInput(stock_code="005930", lookback="1m"))
    assert r.status == "ok"
    p = r.data["period"]
    assert p["return_pct"] == 25.0
    assert p["start_trading_day"] == "2026-06-24"
    assert p["end_trading_day"] == "2026-07-24"
    assert p["lookback"] == "1m"
    assert p["unit"] == "원"


# ── 명시 구간(start/end) ───────────────────────────────────────────
def test_get_prices_explicit_range():
    r = run_get_stock_prices(
        FakeSvc(period=_period()),
        GetStockPricesInput(stock_code="005930", start_date="2026-06-24", end_date="2026-07-24"),
    )
    assert r.status == "ok"
    assert r.data["period"]["return_pct"] == 25.0
    assert r.sources[0].source_type == "price"


# ── no_data ────────────────────────────────────────────────────────
def test_get_prices_no_data_when_quote_none():
    r = run_get_stock_prices(FakeSvc(quote=None), GetStockPricesInput(stock_code="005930"))
    assert r.status == "no_data"
    assert r.sources == []


def test_get_prices_range_no_data():
    r = run_get_stock_prices(
        FakeSvc(period=None),
        GetStockPricesInput(stock_code="005930", start_date="2026-06-24", end_date="2026-07-24"),
    )
    assert r.status == "no_data"


# ── 일봉 요약 ──────────────────────────────────────────────────────
def test_get_prices_daily_summary():
    daily = [
        DailyClose(date(2026, 7, 20 + i), 100000 + i * 100, 0, 0, 0, 1000, "KRW") for i in range(4)
    ]
    svc = FakeSvc(quote=_quote(), period=_period(), daily=daily)
    r = run_get_stock_prices(
        svc, GetStockPricesInput(stock_code="005930", lookback="1m", include_daily=True)
    )
    assert "daily" in r.data
    assert r.data["daily"][0]["trading_day"] == "2026-07-20"
    assert r.data["daily"][0]["close"] == 100000.0


# ── 사건 전후 수익률 ───────────────────────────────────────────────
def test_calculate_event_return_contract():
    ev = PeriodReturn(
        stock_code="005930",
        start_trading_day=date(2026, 7, 21),
        end_trading_day=date(2026, 7, 23),
        start_close=102000.0,
        end_close=106000.0,
        change=4000.0,
        return_pct=3.92,
        currency="KRW",
        adjusted=True,
    )
    r = run_calculate_event_return(
        FakeSvc(event=ev),
        CalculateEventReturnInput(stock_code="005930", event_date="2026-07-22", window="1d"),
    )
    assert r.status == "ok"
    assert r.data["return_pct"] == 3.92
    assert r.data["start_trading_day"] == "2026-07-21"
    assert r.data["end_trading_day"] == "2026-07-23"
    assert "발표 전후" in r.data["note"]  # 인과 아님
    assert len(r.sources) == 2
    assert all(s.source_type == "price" for s in r.sources)


def test_calculate_event_return_lookback_fallback():
    r = run_calculate_event_return(
        FakeSvc(quote=_quote(), period=_period()),
        CalculateEventReturnInput(stock_code="005930", lookback="1m"),
    )
    assert r.status == "ok"
    assert r.data["return_pct"] == 25.0
    assert "최근 1m" in r.data["note"]


def test_calculate_event_return_no_data():
    r = run_calculate_event_return(
        FakeSvc(event=None),
        CalculateEventReturnInput(stock_code="005930", event_date="2026-07-22", window="5d"),
    )
    assert r.status == "no_data"


def test_calculate_event_return_requires_event_or_lookback():
    r = run_calculate_event_return(FakeSvc(), CalculateEventReturnInput(stock_code="005930"))
    assert r.status == "error"


# ── 잘못된 window / lookback ───────────────────────────────────────
def test_bad_window_is_error():
    r = run_calculate_event_return(
        FakeSvc(),
        CalculateEventReturnInput(stock_code="005930", event_date="2026-07-22", window="99d"),
    )
    assert r.status == "error"
