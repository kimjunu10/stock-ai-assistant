"""네이버 금융의 KRX 정규장 일별 시세 어댑터.

토스증권의 캔들에는 KRX와 NXT 거래가 함께 반영될 수 있다. 이 어댑터는
사용자에게 '종가'로 제공하는 과거 OHLCV만 KRX 정규장 기준으로 분리한다.
"""

from __future__ import annotations

from typing import Any

import requests

from app.sources.prices import TossApiError

NAVER_STOCK_API_BASE_URL = "https://m.stock.naver.com"
MAX_PAGE_SIZE = 60


class NaverKrxDailyPriceClient:
    """KRX 정규장 일봉을 기존 StockPriceService 입력 계약으로 변환한다."""

    provider = "naver_krx"
    publisher = "네이버 금융 (KRX)"

    def __init__(
        self,
        *,
        base_url: str = NAVER_STOCK_API_BASE_URL,
        timeout_seconds: float = 15.0,
        session: requests.Session | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds
        self._session = session or requests.Session()

    @staticmethod
    def _number(value: Any) -> str:
        if value is None:
            raise ValueError("missing number")
        return str(value).replace(",", "").strip()

    def fetch_daily_candles_raw(
        self,
        stock_code: str,
        *,
        count: int = 200,
        before: str | None = None,
        adjusted: bool = True,
    ) -> dict[str, Any]:
        """최신순 KRX 일봉과 다음 페이지 번호를 반환한다.

        ``before``는 StockPriceService의 불투명 커서이며 여기서는 페이지 번호다.
        ``adjusted``는 호출 계약 호환용이다. 네이버 응답의 KRX 표시 가격을 그대로 쓴다.
        """

        del adjusted
        page_size = min(max(1, count), MAX_PAGE_SIZE)
        try:
            page = max(1, int(before or "1"))
        except ValueError as exc:
            raise TossApiError("KRX 일봉 페이지 커서가 올바르지 않습니다.") from exc

        try:
            response = self._session.get(
                f"{self._base_url}/api/stock/{stock_code}/price",
                params={"pageSize": page_size, "page": page},
                headers={"Accept": "application/json", "User-Agent": "stock-ai-assistant/1.0"},
                timeout=self._timeout_seconds,
            )
            response.raise_for_status()
            rows = response.json()
        except (requests.RequestException, ValueError) as exc:
            raise TossApiError("KRX 정규장 일봉을 불러오지 못했습니다.") from exc

        if not isinstance(rows, list):
            raise TossApiError("KRX 정규장 일봉 응답 형식이 올바르지 않습니다.")

        candles: list[dict[str, Any]] = []
        try:
            for row in rows:
                day = str(row["localTradedAt"])
                candles.append(
                    {
                        "timestamp": f"{day}T00:00:00+09:00",
                        "openPrice": self._number(row["openPrice"]),
                        "highPrice": self._number(row["highPrice"]),
                        "lowPrice": self._number(row["lowPrice"]),
                        "closePrice": self._number(row["closePrice"]),
                        "volume": self._number(row["accumulatedTradingVolume"]),
                        "currency": "KRW",
                    }
                )
        except (KeyError, TypeError, ValueError) as exc:
            raise TossApiError("KRX 정규장 일봉 응답을 변환하지 못했습니다.") from exc

        return {
            "candles": candles,
            "nextBefore": str(page + 1) if len(rows) == page_size else None,
        }
