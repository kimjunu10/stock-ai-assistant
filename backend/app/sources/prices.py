"""토스증권 Open API 기반 국내주식 현재가·일봉 어댑터."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from datetime import datetime
from typing import Any

import requests

from app.schemas.prices import Candle, StockMarketData, StockQuote

TOSS_OPEN_API_BASE_URL = "https://openapi.tossinvest.com"
SUPPORTED_STOCK_CODES = frozenset({"005930", "000660", "034020", "042660", "005380"})


class TossApiError(RuntimeError):
    """토스증권 인증 또는 시세 응답을 처리할 수 없을 때 발생한다."""


class TossInvestClient:
    """OAuth 토큰과 짧은 시세 캐시를 관리하는 동기식 API 클라이언트."""

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        *,
        base_url: str = TOSS_OPEN_API_BASE_URL,
        timeout_seconds: float = 15.0,
        market_data_cache_seconds: int = 15,
        session: requests.Session | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if not client_id or not client_secret:
            raise ValueError("토스증권 OAuth 자격증명이 필요합니다.")

        self._client_id = client_id
        self._client_secret = client_secret
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds
        self._market_data_cache_seconds = market_data_cache_seconds
        self._session = session or requests.Session()
        self._clock = clock
        self._lock = threading.RLock()
        self._access_token: str | None = None
        self._access_token_expires_at = 0.0
        self._market_data_cache: dict[str, tuple[float, StockMarketData]] = {}

    def get_stock_market_data(self, stock_code: str, *, candle_count: int = 130) -> StockMarketData:
        """현재가와 최근 약 6개월치 수정 일봉을 하나의 응답으로 반환한다."""

        if stock_code not in SUPPORTED_STOCK_CODES:
            raise ValueError("지원하지 않는 종목 코드입니다.")
        if not 2 <= candle_count <= 200:
            raise ValueError("candle_count는 2 이상 200 이하여야 합니다.")

        now = self._clock()
        with self._lock:
            cached = self._market_data_cache.get(stock_code)
            if cached and cached[0] > now:
                return cached[1]

        price_payload = self._request_json(
            "GET",
            "/api/v1/prices",
            params={"symbols": stock_code},
        )
        candle_payload = self._request_json(
            "GET",
            "/api/v1/candles",
            params={
                "symbol": stock_code,
                "interval": "1d",
                "count": candle_count,
                "adjusted": "true",
            },
        )
        market_data = self._normalize_market_data(stock_code, price_payload, candle_payload)

        with self._lock:
            self._market_data_cache[stock_code] = (
                self._clock() + self._market_data_cache_seconds,
                market_data,
            )
        return market_data

    def _get_access_token(self) -> str:
        now = self._clock()
        with self._lock:
            if self._access_token and self._access_token_expires_at > now + 60:
                return self._access_token

            try:
                response = self._session.post(
                    f"{self._base_url}/oauth2/token",
                    data={
                        "grant_type": "client_credentials",
                        "client_id": self._client_id,
                        "client_secret": self._client_secret,
                    },
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                    timeout=self._timeout_seconds,
                )
                response.raise_for_status()
                payload = response.json()
                access_token = str(payload["access_token"])
                expires_in = int(payload.get("expires_in", 3600))
            except (requests.RequestException, KeyError, TypeError, ValueError) as exc:
                raise TossApiError("토스증권 인증에 실패했습니다.") from exc

            self._access_token = access_token
            self._access_token_expires_at = now + max(expires_in, 60)
            return access_token

    def _request_json(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        for attempt in range(2):
            access_token = self._get_access_token()
            try:
                response = self._session.request(
                    method,
                    f"{self._base_url}{path}",
                    params=params,
                    headers={"Authorization": f"Bearer {access_token}"},
                    timeout=self._timeout_seconds,
                )
                if response.status_code == 401 and attempt == 0:
                    with self._lock:
                        self._access_token = None
                        self._access_token_expires_at = 0.0
                    continue
                response.raise_for_status()
                payload = response.json()
            except (requests.RequestException, TypeError, ValueError) as exc:
                raise TossApiError("토스증권 시세 조회에 실패했습니다.") from exc

            if not isinstance(payload, dict):
                raise TossApiError("토스증권 시세 응답 형식이 올바르지 않습니다.")
            return payload

        raise TossApiError("토스증권 액세스 토큰을 갱신하지 못했습니다.")

    def _normalize_market_data(
        self,
        stock_code: str,
        price_payload: dict[str, Any],
        candle_payload: dict[str, Any],
    ) -> StockMarketData:
        try:
            raw_prices = price_payload["result"]
            raw_price = next(item for item in raw_prices if item["symbol"] == stock_code)
            raw_candles = candle_payload["result"]["candles"]
            candles = sorted(
                (
                    Candle(
                        time=datetime.fromisoformat(item["timestamp"]).date().isoformat(),
                        open=self._number(item["openPrice"]),
                        high=self._number(item["highPrice"]),
                        low=self._number(item["lowPrice"]),
                        close=self._number(item["closePrice"]),
                        volume=int(item["volume"]),
                    )
                    for item in raw_candles
                ),
                key=lambda candle: candle.time,
            )
            if len(candles) < 2:
                raise ValueError("비교 가능한 일봉이 부족합니다.")

            last_price = self._number(raw_price["lastPrice"])
            previous_close = candles[-2].close
            change = last_price - previous_close
            change_rate = change / previous_close * 100 if previous_close else 0.0
            quote = StockQuote(
                price=last_price,
                previous_close=previous_close,
                change=change,
                change_rate=round(change_rate, 2),
                currency=str(raw_price["currency"]),
                as_of=datetime.fromisoformat(raw_price["timestamp"]),
                volume=candles[-1].volume,
            )
        except (KeyError, StopIteration, TypeError, ValueError) as exc:
            raise TossApiError("토스증권 시세 응답을 변환하지 못했습니다.") from exc

        return StockMarketData(
            stock_code=stock_code,
            interval="1d",
            period="6m",
            adjusted=True,
            source="토스증권 Open API",
            quote=quote,
            candles=candles,
        )

    @staticmethod
    def _number(value: Any) -> float:
        return float(value)
