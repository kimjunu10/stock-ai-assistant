"""종목 시세 API가 UI 계약을 유지하며 KRX 일봉만 교체하는지 검증한다."""

from __future__ import annotations

from datetime import date, datetime

from app.api.routes.stocks import get_stock_market_data
from app.schemas.prices import Candle, OrderbookLevel, StockMarketData, StockQuote
from app.services.stock_prices import DailyClose


class FakeToss:
    def get_stock_market_data(self, stock_code):
        return StockMarketData(
            stock_code=stock_code,
            interval="1d",
            period="6m",
            adjusted=True,
            source="토스증권 Open API",
            quote=StockQuote(
                price=214000,
                previous_close=220000,
                change=-6000,
                change_rate=-2.73,
                currency="KRW",
                as_of=datetime.fromisoformat("2026-07-29T16:24:00+09:00"),
                volume=100,
            ),
            candles=[
                Candle(
                    time="2026-07-28", open=243000, high=247000, low=216000, close=218000, volume=1
                )
            ],
            intraday_candles=[
                Candle(
                    time="2026-07-29T16:24:00+09:00",
                    open=214000,
                    high=214000,
                    low=214000,
                    close=214000,
                    volume=1,
                )
            ],
            asks=[OrderbookLevel(price=214500, volume=1)],
            bids=[OrderbookLevel(price=214000, volume=1)],
        )


class FakePriceService:
    def get_daily_candles(self, stock_code, *, start, end):
        del stock_code, start, end
        return [
            DailyClose(
                trading_day=date(2026, 7, 27),
                open=257000,
                high=258500,
                low=246000,
                close=254000,
                volume=22_701_316,
                currency="KRW",
            ),
            DailyClose(
                trading_day=date(2026, 7, 28),
                open=238500,
                high=240000,
                low=218500,
                close=220000,
                volume=40_359_563,
                currency="KRW",
            ),
        ]


def test_market_data_keeps_ui_shape_and_replaces_only_daily_candles():
    result = get_stock_market_data("005930", FakeToss(), FakePriceService())

    assert result.quote.price == 214000
    assert result.intraday_candles[0].close == 214000
    assert [c.close for c in result.candles] == [254000, 220000]
    assert result.candles[-1].volume == 40_359_563
    assert result.source == "토스증권 Open API · 네이버 금융 (KRX)"
