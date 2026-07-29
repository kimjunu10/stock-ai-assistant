"""KRX 정규장 일봉 어댑터 단위 테스트."""

from __future__ import annotations

from app.sources.krx_prices import NaverKrxDailyPriceClient


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return FakeResponse(self.payload)


def _row(day: str, *, close: str, volume: int = 100):
    return {
        "localTradedAt": day,
        "openPrice": "238,500",
        "highPrice": "240,000",
        "lowPrice": "218,500",
        "closePrice": close,
        "accumulatedTradingVolume": volume,
    }


def test_converts_krx_rows_to_stock_price_service_contract():
    session = FakeSession(
        [
            _row("2026-07-28", close="220,000", volume=40_359_563),
            _row("2026-07-27", close="254,000", volume=22_701_316),
        ]
    )
    client = NaverKrxDailyPriceClient(session=session)

    result = client.fetch_daily_candles_raw("005930", count=200)

    assert [item["closePrice"] for item in result["candles"]] == ["220000", "254000"]
    assert result["candles"][0]["volume"] == "40359563"
    assert result["nextBefore"] is None
    _, kwargs = session.calls[0]
    assert kwargs["params"] == {"pageSize": 60, "page": 1}


def test_uses_opaque_page_cursor():
    rows = [_row(f"2026-07-{day:02d}", close="220,000") for day in range(1, 11)]
    session = FakeSession(rows)
    client = NaverKrxDailyPriceClient(session=session)

    client.fetch_daily_candles_raw("005930", count=10, before="3")

    _, kwargs = session.calls[0]
    assert kwargs["params"] == {"pageSize": 10, "page": 3}
