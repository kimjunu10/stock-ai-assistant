"""StockPriceService — Phase 6 주가 조회·수익률 계산 (SPEC §7.7·§8.7).

현재가·호가에는 TossInvestClient(app/sources/prices.py)를 재사용하고, 사용자에게
'종가'로 제공하는 과거 OHLCV는 별도 KRX 정규장 일봉 클라이언트를 쓸 수 있다.
현재가의 전일 대비는 토스가 제공한 기준가·등락률을 쓰고, 기간·사건 수익률만
백엔드에서 계산한다. Agent 는 산술하지 않는다.

핵심 규칙:
- 현재가의 등락률은 토스 기준값을 보존하고, 기간·사건 수익률 계산은 이 모듈에서 수행한다.
- 거래일 스냅: 기준일이 휴장이면 목적에 따라 직전/다음 거래일을 명시적으로 선택한다.
- 일봉 count 최대 200 → 긴 구간은 nextBefore 페이징(제한된 페이지 수)으로만 확장.
- 30초 메모리 캐시 + 종목별 fetch lock(동시 중복 호출 방지).
- 429 발생 시 제한된 재시도·대기(무제한 재시도 금지).
- 데이터 없음/미존재 종목 → no_data(다른 날짜·종목으로 대체 금지).
- 모든 시각은 KST(+09:00) 기준. 반환에 실제 조회 시각·거래일을 표시한다.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime
from datetime import time as wall_time
from zoneinfo import ZoneInfo

from app.sources.prices import SUPPORTED_STOCK_CODES, TossApiError, TossInvestClient

# 일봉 어댑터 호출 상한. 실제 어댑터가 더 작은 페이지 크기를 적용할 수 있다.
# 시각은 KST(+09:00) offset 을 명시하므로 별도 변환 없이 그대로 파싱한다.
MAX_CANDLES_PER_CALL = 200
SEOUL_TIMEZONE = ZoneInfo("Asia/Seoul")


class StockPriceError(RuntimeError):
    """주가 서비스 내부 오류(호출부가 안전 메시지로 변환)."""


@dataclass
class DailyClose:
    """정규화된 일봉 종가 1건."""

    trading_day: date
    close: float
    open: float
    high: float
    low: float
    volume: int
    currency: str


@dataclass
class PriceQuote:
    """가장 최근 시세 + 전일 대비(백엔드 계산)."""

    stock_code: str
    price: float
    previous_close: float
    change: float
    change_rate: float  # % , 소수 2자리
    currency: str
    as_of: datetime  # 체결 기준 시각(KST)
    trading_day: date
    # 제공자 현재가 endpoint의 값은 확정 종가로 승격하지 않는다.
    price_kind: str = "current"
    market_status: str = "unknown"
    market_status_as_of: datetime | None = None


def market_status_at(now: datetime) -> str:
    """한국 주식 거래 세션을 요청 현재시각 기준으로 분류한다.

    시세 timestamp는 가격의 기준 시각일 뿐 현재 시장 상태가 아니다. 휴일 캘린더는
    일봉 데이터가 담당하며 여기서는 주말만 확정한다.
    """

    if now.weekday() >= 5:
        return "closed"
    current = now.timetz().replace(tzinfo=None)
    if wall_time(8, 0) <= current < wall_time(8, 50):
        return "pre_market"
    if wall_time(9, 0) <= current < wall_time(15, 30):
        return "regular_open"
    if wall_time(15, 30) <= current < wall_time(15, 40):
        return "session_break"
    if wall_time(15, 40) <= current < wall_time(20, 0):
        return "after_market"
    return "closed"


@dataclass
class PeriodReturn:
    """기간 수익률(백엔드 계산). 시작·종료는 실제 사용된 거래일."""

    stock_code: str
    start_trading_day: date
    end_trading_day: date
    start_close: float
    end_close: float
    change: float
    return_pct: float  # % , 소수 2자리
    currency: str
    adjusted: bool
    # 종료값이 확정 일봉 종가인지, 장중 단일종목 현재가인지 공개 계약에 명시한다.
    end_price_kind: str = "close"


@dataclass
class EventHorizonReturn:
    """사건 발표 후 N거래일 시점의 수익률 1건(백엔드 계산)."""

    horizon_days: int  # 발표 후 몇 번째 확정 거래일인가(1·3·5)
    trading_day: date
    close: float
    change: float
    return_pct: float  # % , 소수 2자리


@dataclass
class EventWindowReturn:
    """사건 발표 전후 주가 계산 결과(계약: 발표 전 마지막 거래일 → 발표 후 N거래일).

    baseline 은 '발표 시점에 시장이 알고 있던 마지막 확정 종가'다. event_date 당일이
    거래일이더라도, 발표 시각을 모르면 당일 종가에는 이미 사건이 반영됐을 수 있으므로
    기본은 발표일 **이전** 마지막 거래일을 baseline 으로 쓴다(보수적).

    horizons 는 발표 후 확정 거래일이 존재하는 만큼만 채운다. 하나도 없으면 빈 목록이며
    (has_post_data=False), 호출부는 다른 기간으로 대체하지 않고 데이터 부족을 반환한다.
    """

    stock_code: str
    event_date: date
    baseline_trading_day: date
    baseline_close: float
    horizons: list[EventHorizonReturn]
    currency: str
    adjusted: bool
    # 발표 전 기준 거래일부터 마지막으로 계산 가능한 지평까지의 실제 일봉.
    # 호출부는 이 값을 다시 조회하거나 계산하지 않고 UI 캔들 차트에 그대로 사용한다.
    daily: list[DailyClose] = field(default_factory=list)

    @property
    def has_post_data(self) -> bool:
        return bool(self.horizons)


@dataclass
class _CacheEntry:
    expires_at: float
    value: object


def _round2(x: float) -> float:
    return round(x, 2)


class StockPriceService:
    """TossInvestClient 를 재사용해 주가를 조회·계산한다. 읽기 전용."""

    def __init__(
        self,
        client: TossInvestClient,
        *,
        daily_client: object | None = None,
        cache_seconds: int = 30,
        rate_limit_retries: int = 2,
        rate_limit_backoff_seconds: float = 1.5,
        max_candle_pages: int = 4,
        clock: Callable[[], float] = time.monotonic,
        now: Callable[[], datetime] | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._client = client
        self._daily_client = daily_client or client
        self.historical_provider = str(getattr(self._daily_client, "provider", "toss"))
        self.historical_publisher = str(
            getattr(self._daily_client, "publisher", "토스증권 Open API")
        )
        self._cache_seconds = cache_seconds
        self._rate_limit_retries = max(0, rate_limit_retries)
        self._rate_limit_backoff = rate_limit_backoff_seconds
        self._max_candle_pages = max(1, max_candle_pages)
        self._clock = clock
        self._now = now or (lambda: datetime.now(SEOUL_TIMEZONE))
        self._sleep = sleep
        self._lock = threading.RLock()
        self._cache: dict[str, _CacheEntry] = {}
        self._fetch_locks: dict[str, threading.Lock] = {}

    # ── 캐시 / 동시성 ────────────────────────────────────────────────
    def _cache_get(self, key: str):
        now = self._clock()
        with self._lock:
            entry = self._cache.get(key)
            if entry and entry.expires_at > now:
                return entry.value
        return None

    def _cache_put(self, key: str, value: object) -> None:
        with self._lock:
            self._cache[key] = _CacheEntry(self._clock() + self._cache_seconds, value)

    def _fetch_lock(self, key: str) -> threading.Lock:
        with self._lock:
            lk = self._fetch_locks.get(key)
            if lk is None:
                lk = threading.Lock()
                self._fetch_locks[key] = lk
            return lk

    # ── 429 백오프 래퍼 ─────────────────────────────────────────────
    def _with_backoff(self, fn: Callable[[], object]):
        """429(rate_limited)에만 제한된 재시도·대기. 그 외 오류는 즉시 전파."""
        attempts = self._rate_limit_retries + 1
        last: TossApiError | None = None
        for i in range(attempts):
            try:
                return fn()
            except TossApiError as exc:
                if getattr(exc, "code", "") != "rate_limited":
                    raise
                last = exc
                if i < attempts - 1:
                    self._sleep(self._rate_limit_backoff * (i + 1))
        assert last is not None
        raise last

    # ── 정규화 ──────────────────────────────────────────────────────
    @staticmethod
    def _to_day(timestamp: str) -> date:
        return datetime.fromisoformat(timestamp).date()

    def _normalize_candles(self, raw: list[dict]) -> list[DailyClose]:
        out: list[DailyClose] = []
        for c in raw:
            try:
                out.append(
                    DailyClose(
                        trading_day=self._to_day(str(c["timestamp"])),
                        close=float(c["closePrice"]),
                        open=float(c["openPrice"]),
                        high=float(c["highPrice"]),
                        low=float(c["lowPrice"]),
                        volume=int(c["volume"]),
                        currency=str(c.get("currency") or "KRW"),
                    )
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise StockPriceError("일봉 응답 정규화 실패") from exc
        # 오름차순(과거→최신) 정렬, 날짜 중복 제거(최신 우선).
        by_day: dict[date, DailyClose] = {}
        for dc in out:
            by_day[dc.trading_day] = dc
        return sorted(by_day.values(), key=lambda d: d.trading_day)

    # ── 일봉 수집(페이징) ───────────────────────────────────────────
    def _collect_daily(
        self, stock_code: str, *, earliest: date, adjusted: bool = True
    ) -> list[DailyClose]:
        """earliest 이상 거래일의 일봉을 최신부터 페이징으로 모은다.

        토스는 newest-first + nextBefore 커서를 준다. earliest 를 덮거나 페이지
        상한에 닿으면 멈춘다(과도한 호출 방지). 미존재 종목은 TossApiError(code=
        stock_not_found)로 올라오며 호출부에서 no_data 처리한다.
        """
        cache_key = f"daily:{stock_code}:{earliest.isoformat()}:{adjusted}"
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached  # type: ignore[return-value]

        with self._fetch_lock(cache_key):
            cached = self._cache_get(cache_key)
            if cached is not None:
                return cached  # type: ignore[return-value]

            collected: dict[date, DailyClose] = {}
            before: str | None = None
            for _ in range(self._max_candle_pages):
                result = self._with_backoff(
                    lambda b=before: self._daily_client.fetch_daily_candles_raw(
                        stock_code, count=MAX_CANDLES_PER_CALL, before=b, adjusted=adjusted
                    )
                )
                page = self._normalize_candles(result.get("candles", []))
                if not page:
                    break
                for dc in page:
                    collected[dc.trading_day] = dc
                oldest = min(dc.trading_day for dc in page)
                next_before = result.get("nextBefore")
                if oldest <= earliest or not next_before:
                    break
                before = str(next_before)

            candles = sorted(collected.values(), key=lambda d: d.trading_day)
            self._cache_put(cache_key, candles)
            return candles

    # ── 거래일 선택 규칙 ────────────────────────────────────────────
    @staticmethod
    def _snap_on_or_before(candles: list[DailyClose], target: date) -> DailyClose | None:
        """target 이하(<=)의 가장 최근 거래일(직전 스냅). 없으면 None."""
        prior = [c for c in candles if c.trading_day <= target]
        return max(prior, key=lambda c: c.trading_day) if prior else None

    @staticmethod
    def _snap_on_or_after(candles: list[DailyClose], target: date) -> DailyClose | None:
        """target 이상(>=)의 가장 이른 거래일(다음 스냅). 없으면 None."""
        after = [c for c in candles if c.trading_day >= target]
        return min(after, key=lambda c: c.trading_day) if after else None

    @staticmethod
    def _snap_strictly_before(candles: list[DailyClose], target: date) -> DailyClose | None:
        """target 미만(<)의 가장 최근 거래일. 사건 baseline 전용(당일 종가 제외)."""
        prior = [c for c in candles if c.trading_day < target]
        return max(prior, key=lambda c: c.trading_day) if prior else None

    # ── 공개 API ────────────────────────────────────────────────────
    def get_current_quote(self, stock_code: str) -> PriceQuote | None:
        """토스 현재가·전일 기준가·등락률. 미존재/데이터 없음이면 None(no_data)."""
        self._require_supported(stock_code)
        cache_key = f"quote:{stock_code}"
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached  # type: ignore[return-value]

        with self._fetch_lock(cache_key):
            cached = self._cache_get(cache_key)
            if cached is not None:
                return cached  # type: ignore[return-value]

            raw = self._with_backoff(lambda: self._client.fetch_live_quote(stock_code))
            if not raw:
                return None
            try:
                price = float(raw["lastPrice"])
                previous_close = float(raw["basePrice"])
                as_of = datetime.fromisoformat(str(raw["timestamp"]))
                currency = str(raw.get("currency") or "KRW")
            except (KeyError, TypeError, ValueError) as exc:
                raise StockPriceError("현재가·전일 기준가 응답 정규화 실패") from exc

            quote_day = as_of.date()
            request_now = self._now()
            market_status = market_status_at(request_now)
            change = price - previous_close
            change_rate = _round2(change / previous_close * 100) if previous_close else 0.0
            quote = PriceQuote(
                stock_code=stock_code,
                price=price,
                previous_close=previous_close,
                change=change,
                change_rate=change_rate,
                currency=currency,
                as_of=as_of,
                trading_day=quote_day,
                price_kind=(
                    "latest"
                    if market_status == "closed" or quote_day != request_now.date()
                    else "current"
                ),
                market_status=market_status,
                market_status_as_of=request_now,
            )
            self._cache_put(cache_key, quote)
            return quote

    def get_period_return(
        self,
        stock_code: str,
        *,
        start: date,
        end: date,
        adjusted: bool = True,
        live_quote: PriceQuote | None = None,
        start_on_or_before: bool = False,
    ) -> PeriodReturn | None:
        """[start, end] 구간 수익률(백엔드 계산). 거래일 스냅 적용.

        일반 lookback 시작일은 첫 거래일(start 이상), 사용자가 특정 날짜를 직접 비교한
        경우(start_on_or_before=True)는 그 날짜가 휴장이면 직전 거래일을 쓴다.
        종료일은 마지막 거래일(end 이하)이며 live_quote가 범위에 있으면 현재가로 끝낸다.
        데이터가 부족하면 None(no_data). 두 기준이 같은 거래일이면 수익률 0으로 유효.
        """
        self._require_supported(stock_code)
        if start > end:
            raise StockPriceError("시작일이 종료일보다 뒤일 수 없습니다.")
        candles = self._collect_daily(
            stock_code, earliest=self._days_before(start, 7), adjusted=adjusted
        )
        if not candles:
            return None
        start_c = (
            self._snap_on_or_before(candles, start)
            if start_on_or_before
            else self._snap_on_or_after(candles, start)
        )
        end_c = self._snap_on_or_before(candles, end)
        use_live_end = (
            live_quote is not None
            and start <= live_quote.trading_day <= end
            and (start_c is None or start_c.trading_day <= live_quote.trading_day)
        )
        if start_c is None or (end_c is None and not use_live_end):
            return None
        end_day = live_quote.trading_day if use_live_end else end_c.trading_day
        end_price = live_quote.price if use_live_end else end_c.close
        if start_c.trading_day > end_day:
            return None
        change = end_price - start_c.close
        return_pct = _round2(change / start_c.close * 100) if start_c.close else 0.0
        return PeriodReturn(
            stock_code=stock_code,
            start_trading_day=start_c.trading_day,
            end_trading_day=end_day,
            start_close=start_c.close,
            end_close=end_price,
            change=change,
            return_pct=return_pct,
            currency=start_c.currency,
            adjusted=adjusted,
            end_price_kind=live_quote.price_kind if use_live_end else "close",
        )

    def get_daily_return(
        self,
        stock_code: str,
        *,
        target_date: date,
        adjusted: bool = True,
    ) -> PeriodReturn | None:
        """target_date의 확정 일봉을 직전 거래일 종가와 비교한다.

        target_date가 휴장일이면 그 이전의 가장 가까운 거래일을 대상일로 삼는다.
        현재가 endpoint는 사용하지 않으므로 과거 일간 등락에 장중 가격이 섞이지 않는다.
        """

        self._require_supported(stock_code)
        candles = self._collect_daily(
            stock_code,
            earliest=self._days_before(target_date, 14),
            adjusted=adjusted,
        )
        if not candles:
            return None
        target = self._snap_on_or_before(candles, target_date)
        if target is None:
            return None
        previous = self._snap_strictly_before(candles, target.trading_day)
        if previous is None:
            return None
        change = target.close - previous.close
        return_pct = _round2(change / previous.close * 100) if previous.close else 0.0
        return PeriodReturn(
            stock_code=stock_code,
            start_trading_day=previous.trading_day,
            end_trading_day=target.trading_day,
            start_close=previous.close,
            end_close=target.close,
            change=change,
            return_pct=return_pct,
            currency=target.currency,
            adjusted=adjusted,
            end_price_kind="close",
        )

    def get_event_return(
        self,
        stock_code: str,
        *,
        event_date: date,
        pre_days: int,
        post_days: int,
        adjusted: bool = True,
    ) -> PeriodReturn | None:
        """사건일 전후 수익률(백엔드 계산).

        pre = event_date 기준 직전 거래일에서 pre_days 만큼 앞선 거래일(시작),
        post = event_date 기준 직후 거래일에서 post_days 만큼 뒤의 거래일(종료).
        event_date 가 휴장이면 목적에 따라: 시작 앵커는 직전 거래일, 종료 앵커는
        직후 거래일로 스냅한다. 데이터 부족 시 None.
        """
        self._require_supported(stock_code)
        candles = self._collect_daily(
            stock_code, earliest=self._days_before(event_date, pre_days * 2 + 14), adjusted=adjusted
        )
        if not candles:
            return None
        # 종료 앵커: 사건일 당일 또는 직전 거래일(발표 시점 가격).
        base = self._snap_on_or_before(candles, event_date)
        # 사건일이 상장 이전 등으로 직전 거래일이 없으면 직후로 스냅.
        if base is None:
            base = self._snap_on_or_after(candles, event_date)
        if base is None:
            return None
        ordered = candles  # 오름차순
        idx = next((i for i, c in enumerate(ordered) if c.trading_day == base.trading_day), None)
        if idx is None:
            return None
        start_idx = idx - pre_days
        end_idx = idx + post_days
        if start_idx < 0 or end_idx >= len(ordered):
            return None
        start_c = ordered[start_idx]
        end_c = ordered[end_idx]
        change = end_c.close - start_c.close
        return_pct = _round2(change / start_c.close * 100) if start_c.close else 0.0
        return PeriodReturn(
            stock_code=stock_code,
            start_trading_day=start_c.trading_day,
            end_trading_day=end_c.trading_day,
            start_close=start_c.close,
            end_close=end_c.close,
            change=change,
            return_pct=return_pct,
            currency=start_c.currency,
            adjusted=adjusted,
        )

    # 사건 후속 질문의 기본 관측 지평(발표 후 N번째 확정 거래일).
    DEFAULT_EVENT_HORIZONS = (1, 3, 5)

    def get_event_window_return(
        self,
        stock_code: str,
        *,
        event_date: date,
        horizons: tuple[int, ...] | list[int] = DEFAULT_EVENT_HORIZONS,
        adjusted: bool = True,
    ) -> EventWindowReturn | None:
        """사건 발표 전 마지막 확정 거래일 대비, 발표 후 1·3·5거래일 수익률을 계산한다.

        get_event_return(대칭 ±N거래일)과 달리 이 메서드는 사건 후속 질문의 계약이다:
        - baseline = event_date **이전** 마지막 확정 거래일 종가(발표 전 마지막 확정값)
        - horizons = event_date **이후** 1·3·5번째 확정 거래일(존재하는 것만)

        발표 후 확정 거래일이 하나도 없으면 horizons 가 비어 has_post_data=False 다.
        이 경우에도 baseline 은 채워 반환하므로 호출부가 "발표 이후 확정 거래일 데이터가
        아직 없다"를 다른 기간으로 대체하지 않고 그대로 답할 수 있다.
        기준 거래일 자체를 찾을 수 없으면(상장 전 등) None.
        """
        self._require_supported(stock_code)
        wanted = sorted({int(h) for h in horizons if int(h) > 0})
        if not wanted:
            raise StockPriceError("관측 지평(horizons)이 비어 있습니다.")
        lookback_days = max(wanted) * 2 + 30
        candles = self._collect_daily(
            stock_code, earliest=self._days_before(event_date, lookback_days), adjusted=adjusted
        )
        if not candles:
            return None
        # baseline: 발표일 '이전' 마지막 확정 거래일(당일 종가에는 사건이 반영됐을 수 있음).
        baseline = self._snap_strictly_before(candles, event_date)
        if baseline is None:
            return None
        base_idx = next(
            (i for i, c in enumerate(candles) if c.trading_day == baseline.trading_day), None
        )
        if base_idx is None:
            return None
        # 발표일 이후(당일 포함) 확정 거래일만 지평 후보로 센다.
        post = [c for c in candles[base_idx + 1 :] if c.trading_day >= event_date]
        result_horizons: list[EventHorizonReturn] = []
        for h in wanted:
            if h > len(post):
                break  # 아직 확정되지 않은 지평 — 추정하지 않는다.
            c = post[h - 1]
            change = c.close - baseline.close
            result_horizons.append(
                EventHorizonReturn(
                    horizon_days=h,
                    trading_day=c.trading_day,
                    close=c.close,
                    change=change,
                    return_pct=_round2(change / baseline.close * 100) if baseline.close else 0.0,
                )
            )
        last_trading_day = (
            result_horizons[-1].trading_day if result_horizons else baseline.trading_day
        )
        window_candles = [
            c for c in candles if baseline.trading_day <= c.trading_day <= last_trading_day
        ]
        return EventWindowReturn(
            stock_code=stock_code,
            event_date=event_date,
            baseline_trading_day=baseline.trading_day,
            baseline_close=baseline.close,
            horizons=result_horizons,
            currency=baseline.currency,
            adjusted=adjusted,
            daily=window_candles,
        )

    def get_daily_candles(
        self, stock_code: str, *, start: date, end: date, adjusted: bool = True
    ) -> list[DailyClose]:
        """[start, end] 구간의 일봉 목록(정규화). 거래일만. 없으면 빈 리스트."""
        self._require_supported(stock_code)
        candles = self._collect_daily(
            stock_code, earliest=self._days_before(start, 7), adjusted=adjusted
        )
        return [c for c in candles if start <= c.trading_day <= end]

    # ── 헬퍼 ────────────────────────────────────────────────────────
    @staticmethod
    def _days_before(d: date, n: int) -> date:
        from datetime import timedelta

        return d - timedelta(days=n)

    @staticmethod
    def _require_supported(stock_code: str) -> None:
        if stock_code not in SUPPORTED_STOCK_CODES:
            raise StockPriceError("지원하지 않는 종목 코드입니다.")
