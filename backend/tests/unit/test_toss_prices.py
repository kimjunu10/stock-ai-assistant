"""토스증권 시세 어댑터 단위 테스트."""

from typing import Any

from app.sources.prices import TossInvestClient


class FakeResponse:
    def __init__(self, payload: dict[str, Any], status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self) -> dict[str, Any]:
        return self._payload


class FakeSession:
    def __init__(self) -> None:
        self.auth_calls = 0
        self.market_calls = 0

    def post(self, *_args: Any, **_kwargs: Any) -> FakeResponse:
        self.auth_calls += 1
        return FakeResponse({"access_token": "token", "expires_in": 3600})

    def request(self, _method: str, url: str, **kwargs: Any) -> FakeResponse:
        self.market_calls += 1
        if url.endswith("/api/v1/prices"):
            symbols = kwargs["params"]["symbols"].split(",")
            return FakeResponse(
                {
                    "result": [
                        {
                            "symbol": symbol,
                            "timestamp": "2026-07-20T15:30:00+09:00",
                            "lastPrice": "72000",
                            "currency": "KRW",
                        }
                        for symbol in symbols
                    ]
                }
            )
        if url.endswith("/api/v1/orderbook"):
            return FakeResponse(
                {
                    "result": {
                        "timestamp": "2026-07-20T15:30:00+09:00",
                        "currency": "KRW",
                        "asks": [{"price": "72100", "volume": "1200"}],
                        "bids": [{"price": "72000", "volume": "5200"}],
                    }
                }
            )
        if url.endswith("/api/v1/price-limits"):
            return FakeResponse(
                {
                    "result": {
                        "timestamp": "2026-07-20T15:30:00+09:00",
                        "upperLimitPrice": "92300",
                        "lowerLimitPrice": "49700",
                        "currency": "KRW",
                    }
                }
            )
        if kwargs["params"]["interval"] == "1m":
            return FakeResponse(
                {
                    "result": {
                        "candles": [
                            {
                                "timestamp": "2026-07-20T15:29:00+09:00",
                                "openPrice": "71900",
                                "highPrice": "72100",
                                "lowPrice": "71800",
                                "closePrice": "72000",
                                "volume": "15200",
                                "currency": "KRW",
                            }
                        ],
                        "nextBefore": None,
                    }
                }
            )
        return FakeResponse(
            {
                "result": {
                    "candles": [
                        {
                            "timestamp": "2026-07-20T00:00:00+09:00",
                            "openPrice": "71000",
                            "highPrice": "72500",
                            "lowPrice": "70800",
                            "closePrice": "72000",
                            "volume": "3100000",
                            "currency": "KRW",
                        },
                        {
                            "timestamp": "2026-07-17T00:00:00+09:00",
                            "openPrice": "70000",
                            "highPrice": "71500",
                            "lowPrice": "69800",
                            "closePrice": "71000",
                            "volume": "2500000",
                            "currency": "KRW",
                        },
                    ],
                    "nextBefore": "2026-07-16T00:00:00+09:00",
                }
            }
        )


def test_market_data_is_normalized_and_cached() -> None:
    session = FakeSession()
    client = TossInvestClient(
        "client-id",
        "client-secret",
        session=session,  # type: ignore[arg-type]
        market_data_cache_seconds=30,
    )

    first = client.get_stock_market_data("005930")
    second = client.get_stock_market_data("005930")

    assert first.quote.price == 72000
    assert first.quote.previous_close == 71000
    assert first.quote.change == 1000
    assert first.quote.change_rate == 1.41
    assert first.quote.currency == "KRW"
    assert first.candles[0].time == "2026-07-17"
    assert first.candles[-1].volume == 3100000
    assert first.intraday_candles[0].time == "2026-07-20T15:29:00+09:00"
    assert first.asks[0].price == 72100
    assert first.bids[0].volume == 5200
    assert first.upper_limit_price == 92300
    assert first.lower_limit_price == 49700
    assert second is first
    assert session.auth_calls == 1
    assert session.market_calls == 5


def test_market_overview_batches_prices_and_caches_previous_closes() -> None:
    session = FakeSession()
    client = TossInvestClient(
        "client-id",
        "client-secret",
        session=session,  # type: ignore[arg-type]
        market_data_cache_seconds=30,
    )

    first = client.get_stock_market_overview()
    second = client.get_stock_market_overview()

    assert len(first.quotes) == 5
    assert first.quotes[0].price == 72000
    assert first.quotes[0].previous_close == 71000
    assert first.quotes[0].change == 1000
    assert first.quotes[0].change_rate == 1.41
    assert second is first
    assert session.auth_calls == 1
    assert session.market_calls == 6
