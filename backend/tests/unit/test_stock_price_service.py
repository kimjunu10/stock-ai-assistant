"""StockPriceService 단위 테스트 (Phase 6).

TossInvestClient 를 가짜로 주입해 거래일 스냅·수익률 계산·30초 캐시·동시 중복 방지·
429 재시도·휴장일·잘못된 종목·no_data·200개 경계·페이징을 검증한다.
수익률 계산 정확성을 고정한다(백엔드 단일 계산 지점).
"""

from __future__ import annotations

from datetime import date

import pytest

from app.services.stock_prices import StockPriceError, StockPriceService
from app.sources.prices import TossApiError


def _mk_candle(day: str, close: float, *, o=None, h=None, low=None, vol=1000):
    return {
        "timestamp": f"{day}T00:00:00.000+09:00",
        "openPrice": str(o if o is not None else close),
        "highPrice": str(h if h is not None else close),
        "lowPrice": str(low if low is not None else close),
        "closePrice": str(close),
        "volume": str(vol),
        "currency": "KRW",
    }


class FakeToss:
    """fetch_reference_quote / fetch_daily_candles_raw 만 구현한 가짜 클라이언트."""

    def __init__(self, candles: list[dict], *, current=None, raise_429_times=0, not_found=False):
        # candles 는 newest-first 로 저장(토스와 동일)
        self.candles = sorted(candles, key=lambda c: c["timestamp"], reverse=True)
        self.current = current
        self.raise_429_times = raise_429_times
        self.not_found = not_found
        self.daily_calls = 0
        self.current_calls = 0

    def fetch_reference_quote(self, stock_code):
        self.current_calls += 1
        if self.not_found:
            return {}
        return self.current or {}

    def fetch_daily_candles_raw(self, stock_code, *, count=200, before=None, adjusted=True):
        self.daily_calls += 1
        if self.raise_429_times > 0:
            self.raise_429_times -= 1
            raise TossApiError("rate", code="rate_limited")
        if self.not_found:
            raise TossApiError("not found", code="stock_not_found")
        rows = self.candles
        if before:
            rows = [c for c in rows if c["timestamp"] < before]
        page = rows[:count]
        next_before = None
        if len(rows) > count:
            next_before = page[-1]["timestamp"]
        return {"candles": page, "nextBefore": next_before}


def _svc(client, **kw):
    kw.setdefault("clock", _fake_clock())
    kw.setdefault("sleep", lambda s: None)
    return StockPriceService(client, **kw)


def _fake_clock():
    t = {"v": 1000.0}

    def clock():
        return t["v"]

    return clock


# ── 현재가 결과 계약 ────────────────────────────────────────────────
def test_current_quote_uses_toss_reference_price_not_daily_close():
    # 일봉 closePrice가 252,500이어도 토스 전일 기준가(basePrice) 249,500을 사용한다.
    candles = [_mk_candle("2026-07-24", 252500), _mk_candle("2026-07-23", 273000)]
    client = FakeToss(
        candles,
        current={
            "symbol": "005930",
            "timestamp": "2026-07-27T12:03:00.000+09:00",
            "lastPrice": "248500",
            "basePrice": "249500",
            "changeRate": "-0.004",
            "currency": "KRW",
        },
    )
    q = _svc(client).get_current_quote("005930")
    assert q is not None
    assert q.price == 248500.0
    assert q.previous_close == 249500.0
    assert q.change == -1000.0
    assert q.change_rate == -0.4
    assert q.trading_day == date(2026, 7, 27)
    assert q.currency == "KRW"
    assert client.daily_calls == 0


def test_current_quote_no_data_when_missing():
    client = FakeToss([], not_found=True)
    assert _svc(client).get_current_quote("005930") is None


# ── 기간 수익률 계산(고정) ─────────────────────────────────────────
def test_period_return_exact():
    candles = [
        _mk_candle("2026-06-24", 200000),
        _mk_candle("2026-07-01", 210000),
        _mk_candle("2026-07-24", 250000),
    ]
    r = _svc(FakeToss(candles)).get_period_return(
        "005930", start=date(2026, 6, 24), end=date(2026, 7, 24)
    )
    assert r is not None
    assert r.start_close == 200000.0
    assert r.end_close == 250000.0
    assert r.return_pct == 25.0  # (250000/200000-1)*100
    assert r.start_trading_day == date(2026, 6, 24)
    assert r.end_trading_day == date(2026, 7, 24)


def test_period_return_no_data():
    r = _svc(FakeToss([])).get_period_return(
        "005930", start=date(2026, 6, 1), end=date(2026, 6, 30)
    )
    assert r is None


# ── 거래일 선택(휴장일 스냅) ───────────────────────────────────────
def test_trading_day_snap_start_after_end_before():
    # 07-25(토)·07-26(일) 휴장. start=07-25 → 다음 거래일 07-27, end=07-26 → 직전 07-24.
    candles = [
        _mk_candle("2026-07-24", 100000),
        _mk_candle("2026-07-27", 110000),
        _mk_candle("2026-07-28", 120000),
    ]
    svc = _svc(FakeToss(candles))
    r = svc.get_period_return("005930", start=date(2026, 7, 27), end=date(2026, 7, 28))
    assert r.start_trading_day == date(2026, 7, 27)
    assert r.end_trading_day == date(2026, 7, 28)
    # end 를 휴장일(07-26)로 주면 직전 거래일 07-24 로 스냅
    r2 = svc.get_period_return("005930", start=date(2026, 7, 24), end=date(2026, 7, 26))
    assert r2.end_trading_day == date(2026, 7, 24)


# ── 사건 전후 수익률 ───────────────────────────────────────────────
def test_event_return_pre_post():
    days = ["2026-07-20", "2026-07-21", "2026-07-22", "2026-07-23", "2026-07-24"]
    prices = [100000, 102000, 104000, 106000, 108000]
    candles = [_mk_candle(d, p) for d, p in zip(days, prices)]
    r = _svc(FakeToss(candles)).get_event_return(
        "005930", event_date=date(2026, 7, 22), pre_days=1, post_days=1
    )
    # base=07-22(104000), pre=07-21(102000), post=07-23(106000)
    assert r.start_close == 102000.0
    assert r.end_close == 106000.0
    assert r.return_pct == pytest.approx(3.92, abs=0.01)  # (106000/102000-1)*100


def test_event_return_holiday_base_snaps_prior():
    # event_date=07-25(토) 휴장 → 직전 거래일 07-24 를 base 로.
    days = ["2026-07-22", "2026-07-23", "2026-07-24", "2026-07-27", "2026-07-28"]
    prices = [100000, 101000, 102000, 103000, 104000]
    candles = [_mk_candle(d, p) for d, p in zip(days, prices)]
    r = _svc(FakeToss(candles)).get_event_return(
        "005930", event_date=date(2026, 7, 25), pre_days=1, post_days=1
    )
    # base=07-24, pre=07-23(101000), post=07-27(103000)
    assert r.start_trading_day == date(2026, 7, 23)
    assert r.end_trading_day == date(2026, 7, 27)


def test_event_return_no_data_insufficient_window():
    candles = [_mk_candle("2026-07-24", 100000)]
    r = _svc(FakeToss(candles)).get_event_return(
        "005930", event_date=date(2026, 7, 24), pre_days=5, post_days=5
    )
    assert r is None


# ── 사건 발표 전후(1·3·5거래일) — fix/phase-7-exit-gate ─────────────
def _event_candles():
    """07-22 발표 기준: 이전 07-21, 이후 07-23/24/27/28/29 (주말 25·26 휴장)."""
    days = [
        "2026-07-20",
        "2026-07-21",
        "2026-07-23",
        "2026-07-24",
        "2026-07-27",
        "2026-07-28",
        "2026-07-29",
    ]
    prices = [99000, 100000, 103000, 104000, 102000, 101000, 98000]
    return [_mk_candle(d, p) for d, p in zip(days, prices)]


def test_event_window_return_1_3_5_trading_days():
    """baseline=발표 전 마지막 거래일, 지평=발표 후 1·3·5번째 확정 거래일."""
    r = _svc(FakeToss(_event_candles())).get_event_window_return(
        "005930", event_date=date(2026, 7, 22)
    )
    assert r.baseline_trading_day == date(2026, 7, 21)
    assert r.baseline_close == 100000.0
    assert r.has_post_data is True
    assert [h.horizon_days for h in r.horizons] == [1, 3, 5]
    # 1거래일=07-23(103000) → +3.0%, 3거래일=07-27(102000) → +2.0%, 5거래일=07-29(98000) → -2.0%
    assert r.horizons[0].trading_day == date(2026, 7, 23)
    assert r.horizons[0].return_pct == pytest.approx(3.0, abs=0.01)
    assert r.horizons[1].trading_day == date(2026, 7, 27)
    assert r.horizons[1].return_pct == pytest.approx(2.0, abs=0.01)
    assert r.horizons[2].trading_day == date(2026, 7, 29)
    assert r.horizons[2].return_pct == pytest.approx(-2.0, abs=0.01)


def test_event_window_baseline_excludes_event_day_close():
    """발표 당일이 거래일이어도 baseline 은 발표 전 거래일(당일 종가는 사건 반영 가능)."""
    days = ["2026-07-21", "2026-07-22", "2026-07-23"]
    candles = [_mk_candle(d, p) for d, p in zip(days, [100000, 110000, 111000])]
    r = _svc(FakeToss(candles)).get_event_window_return(
        "005930", event_date=date(2026, 7, 22), horizons=(1,)
    )
    assert r.baseline_trading_day == date(2026, 7, 21)
    assert r.baseline_close == 100000.0
    # 발표 당일(07-22)이 발표 후 1거래일로 잡힌다.
    assert r.horizons[0].trading_day == date(2026, 7, 22)
    assert r.horizons[0].return_pct == pytest.approx(10.0, abs=0.01)


def test_event_window_no_post_trading_day():
    """발표 이후 확정 거래일이 없으면 has_post_data=False(다른 기간 대체 금지)."""
    days = ["2026-07-20", "2026-07-21"]
    candles = [_mk_candle(d, p) for d, p in zip(days, [99000, 100000])]
    r = _svc(FakeToss(candles)).get_event_window_return("005930", event_date=date(2026, 7, 22))
    assert r is not None
    assert r.has_post_data is False
    assert r.horizons == []
    assert r.baseline_trading_day == date(2026, 7, 21)


def test_event_window_partial_horizons_not_extrapolated():
    """3·5거래일이 아직 없으면 그 지평은 만들지 않는다."""
    days = ["2026-07-21", "2026-07-23", "2026-07-24"]
    candles = [_mk_candle(d, p) for d, p in zip(days, [100000, 103000, 104000])]
    r = _svc(FakeToss(candles)).get_event_window_return("005930", event_date=date(2026, 7, 22))
    assert [h.horizon_days for h in r.horizons] == [1]


def test_event_window_no_baseline_returns_none():
    """발표 전 거래일이 전혀 없으면 None(추정 금지)."""
    candles = [_mk_candle("2026-07-23", 100000)]
    r = _svc(FakeToss(candles)).get_event_window_return("005930", event_date=date(2026, 7, 22))
    assert r is None


# ── 30초 캐시 ──────────────────────────────────────────────────────
def test_daily_cache_hits_within_ttl():
    candles = [_mk_candle("2026-07-24", 100000), _mk_candle("2026-07-23", 99000)]
    clock = _fake_clock()
    client = FakeToss(candles)
    svc = StockPriceService(client, cache_seconds=30, clock=clock, sleep=lambda s: None)
    svc.get_daily_candles("005930", start=date(2026, 7, 1), end=date(2026, 7, 24))
    first = client.daily_calls
    svc.get_daily_candles("005930", start=date(2026, 7, 1), end=date(2026, 7, 24))
    assert client.daily_calls == first  # 캐시 히트로 추가 호출 없음


# ── 동일 요청 중복 방지(fetch lock 존재) ───────────────────────────
def test_concurrent_fetch_lock_exists():
    candles = [_mk_candle("2026-07-24", 100000)]
    svc = _svc(FakeToss(candles))
    # 동일 키 fetch lock 은 재사용된다.
    lk1 = svc._fetch_lock("daily:005930:x")
    lk2 = svc._fetch_lock("daily:005930:x")
    assert lk1 is lk2


# ── 429 제한 재시도 ────────────────────────────────────────────────
def test_rate_limit_retries_then_succeeds():
    candles = [_mk_candle("2026-07-24", 100000), _mk_candle("2026-07-23", 99000)]
    client = FakeToss(candles, raise_429_times=1)
    svc = StockPriceService(
        client,
        rate_limit_retries=2,
        rate_limit_backoff_seconds=0,
        clock=_fake_clock(),
        sleep=lambda s: None,
    )
    out = svc.get_daily_candles("005930", start=date(2026, 7, 1), end=date(2026, 7, 24))
    assert out  # 재시도 후 성공


def test_rate_limit_exhausts_and_raises():
    client = FakeToss([_mk_candle("2026-07-24", 100000)], raise_429_times=10)
    svc = StockPriceService(
        client,
        rate_limit_retries=1,
        rate_limit_backoff_seconds=0,
        clock=_fake_clock(),
        sleep=lambda s: None,
    )
    with pytest.raises(TossApiError) as ei:
        svc.get_daily_candles("005930", start=date(2026, 7, 1), end=date(2026, 7, 24))
    assert ei.value.code == "rate_limited"


# ── 잘못된 종목 ────────────────────────────────────────────────────
def test_unsupported_stock_code_raises():
    svc = _svc(FakeToss([]))
    with pytest.raises(StockPriceError):
        svc.get_current_quote("999999")


def test_not_found_daily_raises_stock_not_found():
    svc = _svc(FakeToss([], not_found=True))
    with pytest.raises(TossApiError) as ei:
        svc.get_daily_candles("005930", start=date(2026, 7, 1), end=date(2026, 7, 24))
    assert ei.value.code == "stock_not_found"


# ── 200개 경계 / 페이징 ────────────────────────────────────────────
def test_paging_expands_beyond_200():
    # 250 거래일 생성(과거→최신). earliest 가 깊으면 2페이지 페이징.
    base = date(2025, 1, 1)
    from datetime import timedelta

    days = [(base + timedelta(days=i)) for i in range(250)]
    candles = [_mk_candle(d.isoformat(), 100000 + i) for i, d in enumerate(days)]
    client = FakeToss(candles)
    svc = StockPriceService(client, max_candle_pages=4, clock=_fake_clock(), sleep=lambda s: None)
    out = svc.get_daily_candles("005930", start=days[0], end=days[-1])
    assert len(out) == 250
    assert client.daily_calls >= 2  # 200 상한 → 최소 2페이지


def test_paging_respects_max_pages():
    from datetime import timedelta

    base = date(2020, 1, 1)
    days = [(base + timedelta(days=i)) for i in range(1000)]
    candles = [_mk_candle(d.isoformat(), 100000 + i) for i, d in enumerate(days)]
    client = FakeToss(candles)
    svc = StockPriceService(client, max_candle_pages=2, clock=_fake_clock(), sleep=lambda s: None)
    svc.get_daily_candles("005930", start=days[0], end=days[-1])
    assert client.daily_calls <= 2  # 페이지 상한 준수(과도한 호출 방지)
