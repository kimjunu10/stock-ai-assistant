"""주가 Tool 계층 단위 테스트 (Phase 6).

run_get_stock_prices / run_calculate_event_return 의 결과 계약·SourceRef·no_data·
숫자/단위/기간·일봉 요약을 검증한다(StockPriceService 를 가짜로 주입).
"""

from __future__ import annotations

from datetime import date, datetime

import pytest
from pydantic import ValidationError

from app.agent.tools.prices import (
    CalculateEventReturnInput,
    GetStockPricesInput,
    run_calculate_event_return,
    run_get_stock_prices,
)
from app.services.stock_prices import (
    DailyClose,
    EventHorizonReturn,
    EventWindowReturn,
    PeriodReturn,
    PriceQuote,
)


class FakeSvc:
    DEFAULT_EVENT_HORIZONS = (1, 3, 5)

    def __init__(self, quote=None, period=None, event=None, daily=None, event_window=None):
        self._quote = quote
        self._period = period
        self._event = event
        self._daily = daily or []
        self._event_window = event_window

    def get_current_quote(self, stock_code):
        return self._quote

    def get_period_return(
        self,
        stock_code,
        *,
        start,
        end,
        adjusted=True,
        live_quote=None,
        start_on_or_before=False,
    ):
        return self._period

    def get_event_return(self, stock_code, *, event_date, pre_days, post_days, adjusted=True):
        return self._event

    def get_event_window_return(self, stock_code, *, event_date, horizons=None, adjusted=True):
        return self._event_window

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


def test_current_price_chart_is_only_previous_close_to_live_price():
    daily = [
        DailyClose(date(2026, 7, 23), 249500, 0, 0, 0, 1000, "KRW"),
        DailyClose(date(2026, 7, 24), 251000, 0, 0, 0, 1000, "KRW"),
    ]
    r = run_get_stock_prices(
        FakeSvc(quote=_quote(), daily=daily),
        GetStockPricesInput(stock_code="005930"),
    )

    assert [point["trading_day"] for point in r.data["daily_full"]] == [
        "2026-07-23",
        "2026-07-24",
    ]
    assert r.data["daily_full"][0]["close"] == 250000.0
    assert r.data["daily_full"][-1]["close"] == 252500.0
    assert r.data["daily_full"][-1]["price_kind"] == "current"


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
        DailyClose(
            date(2026, 7, 20 + i),
            100000 + i * 100,
            99500 + i * 100,
            101000 + i * 100,
            99000 + i * 100,
            1000,
            "KRW",
        )
        for i in range(4)
    ]
    svc = FakeSvc(quote=_quote(), period=_period(), daily=daily)
    r = run_get_stock_prices(
        svc, GetStockPricesInput(stock_code="005930", lookback="1m", include_daily=True)
    )
    assert "daily" in r.data
    assert r.data["daily"][0]["trading_day"] == "2026-07-20"
    assert r.data["daily"][0]["close"] == 100000.0
    assert r.data["daily"][0]["open"] == 99500.0
    assert r.data["daily"][0]["high"] == 101000.0
    assert r.data["daily"][0]["low"] == 99000.0
    assert r.data["daily"][1]["previous_close"] == 100000.0
    assert r.data["daily"][1]["change"] == 100.0
    assert r.data["daily"][1]["change_rate_pct"] == 0.1


# ── 사건 전후 수익률 (fix/phase-7-exit-gate: 일반 기간 대체 차단) ──────
def _event_window(horizons=(1, 3, 5), *, baseline=100000.0):
    """발표 전 마지막 거래일 대비 발표 후 N거래일 결과."""
    closes = {1: 103000.0, 3: 105000.0, 5: 98000.0}
    days = {1: date(2026, 7, 23), 3: date(2026, 7, 27), 5: date(2026, 7, 29)}
    return EventWindowReturn(
        stock_code="005930",
        event_date=date(2026, 7, 22),
        baseline_trading_day=date(2026, 7, 21),
        baseline_close=baseline,
        horizons=[
            EventHorizonReturn(
                horizon_days=h,
                trading_day=days[h],
                close=closes[h],
                change=closes[h] - baseline,
                return_pct=round((closes[h] - baseline) / baseline * 100, 2),
            )
            for h in horizons
        ],
        currency="KRW",
        adjusted=True,
    )


def test_calculate_event_return_contract():
    """발표 전 마지막 거래일 기준 1·3·5거래일 결과와 실제 거래일·출처를 반환한다."""
    r = run_calculate_event_return(
        FakeSvc(event_window=_event_window()),
        CalculateEventReturnInput(
            stock_code="005930", event_date="2026-07-22", event_id="news:evt-1"
        ),
    )
    assert r.status == "ok"
    assert r.data["basis"] == "event"
    assert r.data["event_id"] == "news:evt-1"
    assert r.data["event_date"] == "2026-07-22"
    assert r.data["baseline_trading_day"] == "2026-07-21"
    assert [h["horizon_days"] for h in r.data["horizons"]] == [1, 3, 5]
    assert r.data["horizons"][0]["return_pct"] == 3.0
    assert r.data["horizons"][2]["return_pct"] == -2.0
    # 실제 사용한 시작·종료 거래일
    assert r.data["start_trading_day"] == "2026-07-21"
    assert r.data["end_trading_day"] == "2026-07-29"
    assert "발표 전 마지막 거래일" in r.data["note"]  # 인과 아님
    # baseline 1건 + 지평 3건
    assert len(r.sources) == 4
    assert all(s.source_type == "price" for s in r.sources)


def test_calculate_event_return_partial_horizons():
    """확정된 거래일까지만 반환하고 나머지를 추정하지 않는다."""
    r = run_calculate_event_return(
        FakeSvc(event_window=_event_window(horizons=(1,))),
        CalculateEventReturnInput(stock_code="005930", event_date="2026-07-22"),
    )
    assert r.status == "ok"
    assert [h["horizon_days"] for h in r.data["horizons"]] == [1]
    assert r.data["end_trading_day"] == "2026-07-23"


def test_calculate_event_return_no_post_trading_day():
    """발표 이후 확정 거래일이 없으면 no_data — 다른 기간으로 대체하지 않는다."""
    r = run_calculate_event_return(
        FakeSvc(event_window=_event_window(horizons=())),
        CalculateEventReturnInput(stock_code="005930", event_date="2026-07-22"),
    )
    assert r.status == "no_data"
    assert r.data["has_post_data"] is False
    assert r.data["basis"] == "event"
    # 상태 설명은 있어도 수익률 수치는 만들지 않는다.
    assert "return_pct" not in r.data
    assert any("확정 거래일 데이터가" in w for w in r.warnings)


def test_calculate_event_return_no_baseline():
    r = run_calculate_event_return(
        FakeSvc(event_window=None),
        CalculateEventReturnInput(stock_code="005930", event_date="2026-07-22"),
    )
    assert r.status == "no_data"


def test_calculate_event_return_requires_event_date():
    """event_date 없이는 Tool 입력 자체가 성립하지 않는다(기간 대체 차단)."""
    with pytest.raises(ValidationError):
        CalculateEventReturnInput(stock_code="005930")


def test_calculate_event_return_rejects_lookback_field():
    """일반 기간 인자(lookback)는 이 Tool 계약에서 제거됐다."""
    assert "lookback" not in CalculateEventReturnInput.model_fields


def test_calculate_event_return_bad_event_date():
    r = run_calculate_event_return(
        FakeSvc(event_window=_event_window()),
        CalculateEventReturnInput(stock_code="005930", event_date="2026-13-99"),
    )
    assert r.status == "error"


# ── 잘못된 window ─────────────────────────────────────────────────
def test_bad_window_is_error():
    r = run_calculate_event_return(
        FakeSvc(),
        CalculateEventReturnInput(stock_code="005930", event_date="2026-07-22", window="99d"),
    )
    assert r.status == "error"
