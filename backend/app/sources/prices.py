"""토스증권 Open API 기반 국내주식 현재가·일봉 어댑터."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from datetime import datetime
from typing import Any

import requests

from app.schemas.prices import (
    Candle,
    OrderbookLevel,
    StockCompanyProfile,
    StockListQuote,
    StockMarketData,
    StockMarketOverview,
    StockQuote,
)

TOSS_OPEN_API_BASE_URL = "https://openapi.tossinvest.com"
SUPPORTED_STOCK_CODES = frozenset({"005930", "000660", "034020", "042660", "005380"})


class TossApiError(RuntimeError):
    """토스증권 인증 또는 시세 응답을 처리할 수 없을 때 발생한다."""

    def __init__(self, message: str, *, code: str = "toss_api_error") -> None:
        super().__init__(message)
        self.code = code


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
        self._market_overview_cache: tuple[float, StockMarketOverview] | None = None
        self._reference_quotes_cache: tuple[float, dict[str, dict[str, Any]]] | None = None
        self._reference_quotes_fetch_lock = threading.Lock()
        self._stock_info_cache: dict[str, StockCompanyProfile] = {}
        self._market_data_fetch_locks = {
            stock_code: threading.Lock() for stock_code in SUPPORTED_STOCK_CODES
        }
        self._stock_info_fetch_locks = {
            stock_code: threading.Lock() for stock_code in SUPPORTED_STOCK_CODES
        }

    def get_stock_market_overview(self) -> StockMarketOverview:
        """지원 종목 전체의 현재가를 한 번에 조회해 목록 화면에 제공한다."""

        now = self._clock()
        with self._lock:
            if self._market_overview_cache and self._market_overview_cache[0] > now:
                return self._market_overview_cache[1]

        stock_codes = sorted(SUPPORTED_STOCK_CODES)
        reference_quotes = self._get_market_reference_quotes()
        try:
            quotes = []
            for stock_code in stock_codes:
                raw_quote = reference_quotes[stock_code]
                price = self._number(raw_quote["lastPrice"])
                previous_close = self._number(raw_quote["basePrice"])
                change = price - previous_close
                quotes.append(
                    StockListQuote(
                        stock_code=stock_code,
                        price=price,
                        previous_close=previous_close,
                        change=change,
                        change_rate=round(self._number(raw_quote["changeRate"]) * 100, 2),
                        as_of=datetime.fromisoformat(raw_quote["timestamp"]),
                    )
                )
        except (KeyError, TypeError, ValueError) as exc:
            raise TossApiError("토스증권 전일 기준가 응답을 변환하지 못했습니다.") from exc

        overview = StockMarketOverview(source="토스증권 Open API", quotes=quotes)
        with self._lock:
            self._market_overview_cache = (
                self._clock() + self._market_data_cache_seconds,
                overview,
            )
        return overview

    # ── Phase 6 주가 Tool 용 read-only raw fetch ──────────────────────────
    # 인증·토큰 갱신·timeout·401 재시도는 기존 _request_json/_get_access_token 를
    # 그대로 재사용한다(중복 클라이언트 아님). 정규화·계산은 상위 서비스가 담당한다.

    def fetch_current_price(self, stock_code: str) -> dict[str, Any]:
        """단일 종목 현재가 원본(symbol/timestamp/lastPrice/currency)을 반환한다.

        토스 /prices 는 미존재 종목에 대해 빈 result 를 주므로, 그 경우 빈 dict 를
        반환한다(호출부가 no_data 로 처리; 여기서 예외를 던지지 않는다).
        """
        payload = self._request_json("GET", "/api/v1/prices", params={"symbols": stock_code})
        try:
            for row in payload["result"]:
                if row.get("symbol") == stock_code:
                    return row
        except (KeyError, TypeError) as exc:
            raise TossApiError("토스증권 현재가 응답을 변환하지 못했습니다.") from exc
        return {}

    def fetch_reference_quote(self, stock_code: str) -> dict[str, Any]:
        """토스 전일 기준가가 포함된 실시간 시세를 반환한다.

        MARKET_TRADING_AMOUNT 랭킹의 ``price.basePrice``와 ``price.changeRate``는
        공식 OpenAPI 계약상 duration과 무관하게 항상 전일 기준이다. 일봉 closePrice는
        KRX·NXT 세션을 합친 값일 수 있으므로 전일 대비 계산에 사용하지 않는다.
        """

        return self._get_market_reference_quotes().get(stock_code, {})

    def _get_market_reference_quotes(self) -> dict[str, dict[str, Any]]:
        now = self._clock()
        with self._lock:
            cached = self._reference_quotes_cache
            if cached and cached[0] > now:
                return cached[1]

        with self._reference_quotes_fetch_lock:
            now = self._clock()
            with self._lock:
                cached = self._reference_quotes_cache
                if cached and cached[0] > now:
                    return cached[1]

            payload = self._request_json(
                "GET",
                "/api/v1/rankings",
                params={
                    "type": "MARKET_TRADING_AMOUNT",
                    "marketCountry": "KR",
                    "duration": "realtime",
                    "count": 100,
                },
            )
            try:
                result = payload["result"]
                ranked_at = result["rankedAt"]
                if not isinstance(ranked_at, str):
                    raise TypeError("rankedAt must be a string")
                quotes = {
                    str(item["symbol"]): {
                        "symbol": str(item["symbol"]),
                        "timestamp": ranked_at,
                        "lastPrice": item["price"]["lastPrice"],
                        "basePrice": item["price"]["basePrice"],
                        "changeRate": item["price"]["changeRate"],
                        "currency": item["currency"],
                    }
                    for item in result["rankings"]
                }
            except (KeyError, TypeError, ValueError) as exc:
                raise TossApiError("토스증권 전일 기준가 응답을 변환하지 못했습니다.") from exc

            with self._lock:
                self._reference_quotes_cache = (
                    self._clock() + self._market_data_cache_seconds,
                    quotes,
                )
            return quotes

    def fetch_daily_candles_raw(
        self, stock_code: str, *, count: int = 200, before: str | None = None, adjusted: bool = True
    ) -> dict[str, Any]:
        """일봉 원본 페이지 1개(result.candles + nextBefore)를 반환한다.

        count 는 토스 제한(1~200)을 따른다. before 는 nextBefore 커서(그 시각 이전).
        미존재 종목이면 토스가 404 를 주며 _request_json 이 TossApiError 로 변환한다.
        """
        if not 1 <= count <= 200:
            raise ValueError("count 는 1 이상 200 이하여야 합니다.")
        params: dict[str, Any] = {
            "symbol": stock_code,
            "interval": "1d",
            "count": count,
            "adjusted": "true" if adjusted else "false",
        }
        if before:
            params["before"] = before
        payload = self._request_json("GET", "/api/v1/candles", params=params)
        try:
            result = payload["result"]
            if not isinstance(result.get("candles"), list):
                raise TossApiError("토스증권 일봉 응답을 변환하지 못했습니다.")
        except (KeyError, TypeError) as exc:
            raise TossApiError("토스증권 일봉 응답을 변환하지 못했습니다.") from exc
        return result

    def fetch_intraday_candles_raw(self, stock_code: str, quote_date: str) -> list[dict[str, Any]]:
        """당일 1분봉 원본 목록을 반환한다(기존 nextBefore 페이지네이션 재사용)."""
        return self._get_intraday_candles(stock_code, quote_date)["result"]["candles"]

    def get_stock_market_data(self, stock_code: str, *, candle_count: int = 130) -> StockMarketData:
        """현재가, 일봉, 1분봉, 호가와 가격 제한을 하나의 응답으로 반환한다."""

        if stock_code not in SUPPORTED_STOCK_CODES:
            raise ValueError("지원하지 않는 종목 코드입니다.")
        if not 2 <= candle_count <= 200:
            raise ValueError("candle_count는 2 이상 200 이하여야 합니다.")

        with self._market_data_fetch_locks[stock_code]:
            now = self._clock()
            with self._lock:
                cached = self._market_data_cache.get(stock_code)
                if cached and cached[0] > now:
                    return cached[1]

            reference_quote = self.fetch_reference_quote(stock_code)
            if not reference_quote:
                raise TossApiError("토스증권 전일 기준가를 확인할 수 없습니다.")
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
            quote_date = datetime.fromisoformat(reference_quote["timestamp"]).date().isoformat()
            intraday_payload = self._get_intraday_candles(stock_code, quote_date)
            orderbook_payload = self._request_json(
                "GET", "/api/v1/orderbook", params={"symbol": stock_code}
            )
            price_limit_payload = self._request_json(
                "GET", "/api/v1/price-limits", params={"symbol": stock_code}
            )
            market_data = self._normalize_market_data(
                stock_code,
                reference_quote,
                candle_payload,
                intraday_payload,
                orderbook_payload,
                price_limit_payload,
            )

            with self._lock:
                self._market_data_cache[stock_code] = (
                    self._clock() + self._market_data_cache_seconds,
                    market_data,
                )
            return market_data

    def get_stock_info(
        self,
        stock_code: str,
        *,
        dart_profile: dict[str, Any] | None = None,
    ) -> StockCompanyProfile:
        """토스 종목 마스터와 저장된 DART 기업개황을 합친다."""

        if stock_code not in SUPPORTED_STOCK_CODES:
            raise ValueError("지원하지 않는 종목 코드입니다.")
        with self._stock_info_fetch_locks[stock_code]:
            with self._lock:
                cached = self._stock_info_cache.get(stock_code)
            if cached:
                return cached

            payload = self._request_json(
                "GET",
                "/api/v1/stocks",
                params={"symbols": stock_code},
            )
            try:
                item = next(row for row in payload["result"] if row["symbol"] == stock_code)
                profile = dart_profile or {}
                homepage = self._website(profile.get("hm_url"))
                result = StockCompanyProfile(
                    stock_code=stock_code,
                    name=str(profile.get("stock_name") or item["name"]),
                    english_name=str(profile.get("corp_name_eng") or item.get("englishName") or "")
                    or None,
                    market=str(item["market"]),
                    ceo=str(profile.get("ceo_nm") or "") or None,
                    established_date=str(profile.get("est_dt") or "") or None,
                    list_date=str(item.get("listDate") or "") or None,
                    shares_outstanding=(
                        int(item["sharesOutstanding"])
                        if item.get("sharesOutstanding") is not None
                        else None
                    ),
                    homepage=homepage,
                    industry_code=str(profile.get("induty_code") or "") or None,
                )
            except (KeyError, StopIteration, TypeError, ValueError) as exc:
                raise TossApiError("토스증권 종목 정보 응답을 변환하지 못했습니다.") from exc

            with self._lock:
                self._stock_info_cache[stock_code] = result
            return result

    def _get_intraday_candles(self, stock_code: str, quote_date: str) -> dict[str, Any]:
        """공식 nextBefore 페이지네이션으로 당일 1분봉 전체를 수집한다."""

        candles_by_time: dict[str, dict[str, Any]] = {}
        before: str | None = None
        # 국내 NXT 세션까지 포함해도 4 × 200봉이면 하루 전체를 덮는다.
        for _ in range(4):
            params: dict[str, Any] = {
                "symbol": stock_code,
                "interval": "1m",
                "count": 200,
                "adjusted": "true",
            }
            if before:
                params["before"] = before
            payload = self._request_json("GET", "/api/v1/candles", params=params)
            try:
                page = payload["result"]
                page_candles = page["candles"]
            except (KeyError, TypeError) as exc:
                raise TossApiError("토스증권 1분봉 응답을 변환하지 못했습니다.") from exc

            reached_previous_day = False
            for candle in page_candles:
                timestamp = str(candle["timestamp"])
                if datetime.fromisoformat(timestamp).date().isoformat() == quote_date:
                    candles_by_time[timestamp] = candle
                else:
                    reached_previous_day = True
            next_before = page.get("nextBefore")
            if reached_previous_day or not next_before or not page_candles:
                break
            before = str(next_before)

        return {"result": {"candles": list(candles_by_time.values()), "nextBefore": before}}

    @staticmethod
    def _website(value: Any) -> str | None:
        text = str(value or "").strip()
        if not text:
            return None
        return text if text.startswith(("http://", "https://")) else f"https://{text}"

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
                if response.status_code >= 400:
                    try:
                        error_payload = response.json()
                    except (TypeError, ValueError):
                        error_payload = {}
                    error_code = str(error_payload.get("error") or "")
                    error_description = str(error_payload.get("error_description") or "")
                    is_ip_blocked = (
                        response.status_code == 403
                        and "IP address not allowed" in error_description
                    )
                    if is_ip_blocked:
                        raise TossApiError(
                            "현재 서버 IP가 토스증권 Open API 허용 목록에 없습니다.",
                            code="ip_not_allowed",
                        )
                    raise TossApiError(
                        error_description or "토스증권 인증 요청이 거부됐습니다.",
                        code=error_code or "auth_failed",
                    )
                response.raise_for_status()
                payload = response.json()
                access_token = str(payload["access_token"])
                expires_in = int(payload.get("expires_in", 3600))
            except TossApiError:
                raise
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
                # rate limit·미존재 종목은 상위(주가 서비스)가 백오프·no_data 로
                # 구분 처리할 수 있게 전용 code 를 붙인다(기존 예외 흐름은 유지).
                if response.status_code == 429:
                    raise TossApiError("토스증권 요청 한도를 초과했습니다.", code="rate_limited")
                if response.status_code == 404:
                    raise TossApiError(
                        "토스증권에서 종목을 찾을 수 없습니다.", code="stock_not_found"
                    )
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
        reference_quote: dict[str, Any],
        candle_payload: dict[str, Any],
        intraday_payload: dict[str, Any],
        orderbook_payload: dict[str, Any],
        price_limit_payload: dict[str, Any],
    ) -> StockMarketData:
        try:
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
            intraday_candles = sorted(
                (
                    Candle(
                        time=item["timestamp"],
                        open=self._number(item["openPrice"]),
                        high=self._number(item["highPrice"]),
                        low=self._number(item["lowPrice"]),
                        close=self._number(item["closePrice"]),
                        volume=int(item["volume"]),
                    )
                    for item in intraday_payload["result"]["candles"]
                ),
                key=lambda candle: candle.time,
            )
            if len(candles) < 2:
                raise ValueError("비교 가능한 일봉이 부족합니다.")

            raw_orderbook = orderbook_payload["result"]
            asks = [
                OrderbookLevel(price=self._number(item["price"]), volume=int(item["volume"]))
                for item in raw_orderbook["asks"][:5]
            ]
            bids = [
                OrderbookLevel(price=self._number(item["price"]), volume=int(item["volume"]))
                for item in raw_orderbook["bids"][:5]
            ]
            raw_limits = price_limit_payload["result"]

            last_price = self._number(reference_quote["lastPrice"])
            previous_close = self._number(reference_quote["basePrice"])
            change = last_price - previous_close
            quote = StockQuote(
                price=last_price,
                previous_close=previous_close,
                change=change,
                change_rate=round(self._number(reference_quote["changeRate"]) * 100, 2),
                currency=str(reference_quote["currency"]),
                as_of=datetime.fromisoformat(reference_quote["timestamp"]),
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
            intraday_candles=intraday_candles,
            upper_limit_price=(
                self._number(raw_limits["upperLimitPrice"])
                if raw_limits.get("upperLimitPrice") is not None
                else None
            ),
            lower_limit_price=(
                self._number(raw_limits["lowerLimitPrice"])
                if raw_limits.get("lowerLimitPrice") is not None
                else None
            ),
            asks=asks,
            bids=bids,
        )

    @staticmethod
    def _number(value: Any) -> float:
        return float(value)
