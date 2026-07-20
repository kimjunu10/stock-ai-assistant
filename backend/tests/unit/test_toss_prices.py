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

    def request(self, _method: str, url: str, **_kwargs: Any) -> FakeResponse:
        self.market_calls += 1
        if url.endswith("/api/v1/prices"):
            return FakeResponse(
                {
                    "result": [
                        {
                            "symbol": "005930",
                            "timestamp": "2026-07-20T15:30:00+09:00",
                            "lastPrice": "72000",
                            "currency": "KRW",
                        }
                    ]
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
    assert second is first
    assert session.auth_calls == 1
    assert session.market_calls == 2
