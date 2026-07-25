"""주가 Tool (Phase 6, SPEC §7.7·§8.7).

get_stock_prices: 현재가·전일대비·지정 기간·최근 N거래일·(요청 시)분봉.
calculate_event_return: 특정일/사건/기간 전후 수익률(백엔드 계산).

원칙:
- 수익률·등락은 StockPriceService(백엔드)만 계산. Tool·Agent 는 산술하지 않는다.
- 반환은 계산 완료 값 + SourceRef(source_type="price")만. 원시 캔들 배열은 최소화.
- no_data 와 error 구분. 데이터 없으면 다른 날짜·종목으로 대체 금지.
- 모든 날짜/기간 키워드는 정규화 집합만 허용(Agent 자유 파싱 차단).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from pydantic import BaseModel, Field

from app.agent.tools.common import SourceRef, ToolResult, error, no_data, ok, sanitize_exception
from app.services.stock_prices import (
    PeriodReturn,
    PriceQuote,
    StockPriceError,
    StockPriceService,
)
from app.sources.prices import TossApiError

# 기간 키워드 → 달력일 근사(거래일 스냅은 서비스가 담당). 자유 서술 대신 이 집합만 허용.
LOOKBACK_DAYS = {
    "1w": 7,
    "2w": 14,
    "1m": 30,
    "3m": 90,
    "6m": 180,
    "1y": 365,
}
# 사건 전후 window 키워드 → (pre_days, post_days) 거래일 수.
EVENT_WINDOWS = {
    "1d": (1, 1),
    "3d": (3, 3),
    "5d": (5, 5),
    "10d": (10, 10),
}
_DATA_SOURCE = "토스증권 Open API"


class GetStockPricesInput(BaseModel):
    stock_code: str = Field(pattern=r"^[0-9]{6}$")
    # 기간 미지정 → 현재가만. lookback 지정 → 기간 수익률+시작/종료 거래일.
    lookback: str | None = None  # LOOKBACK_DAYS 키만 유효
    start_date: str | None = None  # YYYY-MM-DD (명시 구간)
    end_date: str | None = None  # YYYY-MM-DD
    include_daily: bool = False  # 일봉 목록 포함 여부(기본 미포함, 요약만)


class CalculateEventReturnInput(BaseModel):
    stock_code: str = Field(pattern=r"^[0-9]{6}$")
    # 사건 기준일(뉴스·공시 발표일). 미지정 시 lookback 기간 수익률로 대체.
    event_date: str | None = None  # YYYY-MM-DD
    window: str = "5d"  # EVENT_WINDOWS 키
    lookback: str | None = None  # event_date 없을 때 기간 수익률(1w/1m 등)


def _parse_date(s: str | None) -> date | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s).date()
    except ValueError:
        return None


def _price_source(stock_code: str, *, trading_day: date, as_of: str, extra: dict) -> SourceRef:
    """주가 결과 출처 1건. source_id 는 재조회 가능한 결정적 키."""
    locator = {"stock_code": stock_code, "interval": "1d", "provider": "toss", **extra}
    return SourceRef(
        source_id=f"price:{stock_code}:{trading_day.isoformat()}",
        source_type="price",
        title=f"{stock_code} 주가 · {trading_day.isoformat()}",
        publisher=_DATA_SOURCE,
        published_at=trading_day.isoformat(),
        value_kind="actual",
        locator={**locator, "as_of": as_of},
    )


def _quote_payload(q: PriceQuote) -> dict:
    return {
        "stock_code": q.stock_code,
        "price": q.price,
        "previous_close": q.previous_close,
        "change": q.change,
        "change_rate_pct": q.change_rate,
        "currency": q.currency,
        "trading_day": q.trading_day.isoformat(),
        "as_of": q.as_of.isoformat(),
        "unit": "원",
    }


def _return_payload(r: PeriodReturn) -> dict:
    return {
        "stock_code": r.stock_code,
        "start_trading_day": r.start_trading_day.isoformat(),
        "end_trading_day": r.end_trading_day.isoformat(),
        "start_close": r.start_close,
        "end_close": r.end_close,
        "change": r.change,
        "return_pct": r.return_pct,
        "currency": r.currency,
        "adjusted": r.adjusted,
        "unit": "원",
    }


def run_get_stock_prices(svc: StockPriceService, inp: GetStockPricesInput) -> ToolResult:
    """현재가 또는 지정 기간 가격을 반환한다(수익률은 서비스가 계산)."""
    try:
        # (1) 명시 구간(start/end) → 기간 수익률 + 선택적 일봉.
        start = _parse_date(inp.start_date)
        end = _parse_date(inp.end_date)
        if start and end:
            r = svc.get_period_return(inp.stock_code, start=start, end=end)
            if r is None:
                return no_data(
                    f"{inp.stock_code} {start}~{end} 구간의 거래일 데이터가 없습니다. "
                    "다른 기간으로 대체하지 않았습니다."
                )
            data = {"quote": None, "period": _return_payload(r)}
            sources = [
                _price_source(
                    inp.stock_code,
                    trading_day=r.end_trading_day,
                    as_of=r.end_trading_day.isoformat(),
                    extra={"start": r.start_trading_day.isoformat(), "adjusted": r.adjusted},
                )
            ]
            if inp.include_daily:
                data["daily"] = _daily_summary(svc, inp.stock_code, start, end)
            return ok(data, sources=sources)

        # (2) 현재가(항상). lookback 있으면 기간 수익률도 함께.
        q = svc.get_current_quote(inp.stock_code)
        if q is None:
            return no_data(
                f"{inp.stock_code} 현재가 데이터를 확인할 수 없습니다"
                "(미존재 종목이거나 데이터 없음)."
            )
        data = {"quote": _quote_payload(q), "period": None}
        sources = [
            _price_source(
                inp.stock_code,
                trading_day=q.trading_day,
                as_of=q.as_of.isoformat(),
                extra={"kind": "current"},
            )
        ]

        if inp.lookback:
            days = LOOKBACK_DAYS.get(inp.lookback)
            if days is None:
                return error(f"지원하지 않는 기간입니다: {inp.lookback}")
            start = q.trading_day - timedelta(days=days)
            r = svc.get_period_return(inp.stock_code, start=start, end=q.trading_day)
            if r is not None:
                data["period"] = _return_payload(r)
                data["period"]["lookback"] = inp.lookback
                sources.append(
                    _price_source(
                        inp.stock_code,
                        trading_day=r.start_trading_day,
                        as_of=r.start_trading_day.isoformat(),
                        extra={"kind": "period_start", "adjusted": r.adjusted},
                    )
                )
        if inp.include_daily and inp.lookback:
            data["daily"] = _daily_summary(
                svc,
                inp.stock_code,
                q.trading_day - timedelta(days=LOOKBACK_DAYS[inp.lookback]),
                q.trading_day,
            )
        return ok(data, sources=sources)

    except StockPriceError as e:
        return error(str(e))
    except TossApiError as e:
        if getattr(e, "code", "") == "stock_not_found":
            return no_data(f"{inp.stock_code} 종목을 찾을 수 없습니다.")
        return error(sanitize_exception(e))
    except Exception as e:  # noqa: BLE001
        return error(sanitize_exception(e))


def run_calculate_event_return(
    svc: StockPriceService, inp: CalculateEventReturnInput
) -> ToolResult:
    """특정일/사건 전후 또는 기간 수익률을 반환한다(백엔드 계산)."""
    try:
        event_date = _parse_date(inp.event_date)
        if event_date is not None:
            window = EVENT_WINDOWS.get(inp.window)
            if window is None:
                return error(f"지원하지 않는 window 입니다: {inp.window}")
            pre_days, post_days = window
            r = svc.get_event_return(
                inp.stock_code,
                event_date=event_date,
                pre_days=pre_days,
                post_days=post_days,
            )
            if r is None:
                return no_data(
                    f"{inp.stock_code} {event_date} 전후 거래일 데이터가 부족합니다. "
                    "다른 기간으로 대체하지 않았습니다."
                )
            return _event_ok(inp.stock_code, r, note=f"{event_date} 발표 전후(±{pre_days}거래일)")

        # event_date 없으면 lookback 기간 수익률.
        if not inp.lookback:
            return error("event_date 또는 lookback 중 하나는 필요합니다.")
        days = LOOKBACK_DAYS.get(inp.lookback)
        if days is None:
            return error(f"지원하지 않는 기간입니다: {inp.lookback}")
        q = svc.get_current_quote(inp.stock_code)
        if q is None:
            return no_data(f"{inp.stock_code} 기준 현재가를 확인할 수 없습니다.")
        start = q.trading_day - timedelta(days=days)
        r = svc.get_period_return(inp.stock_code, start=start, end=q.trading_day)
        if r is None:
            return no_data(f"{inp.stock_code} 최근 {inp.lookback} 구간 데이터가 없습니다.")
        return _event_ok(inp.stock_code, r, note=f"최근 {inp.lookback}")

    except StockPriceError as e:
        return error(str(e))
    except TossApiError as e:
        if getattr(e, "code", "") == "stock_not_found":
            return no_data(f"{inp.stock_code} 종목을 찾을 수 없습니다.")
        return error(sanitize_exception(e))
    except Exception as e:  # noqa: BLE001
        return error(sanitize_exception(e))


def _event_ok(stock_code: str, r: PeriodReturn, *, note: str) -> ToolResult:
    data = _return_payload(r)
    data["note"] = note  # 인과 아님(시간적 관계만)
    sources = [
        _price_source(
            stock_code,
            trading_day=r.start_trading_day,
            as_of=r.start_trading_day.isoformat(),
            extra={"kind": "return_start", "adjusted": r.adjusted},
        ),
        _price_source(
            stock_code,
            trading_day=r.end_trading_day,
            as_of=r.end_trading_day.isoformat(),
            extra={"kind": "return_end", "adjusted": r.adjusted},
        ),
    ]
    return ok(data, sources=sources)


def _daily_summary(svc: StockPriceService, stock_code: str, start: date, end: date) -> list[dict]:
    """일봉 요약(최대 앞뒤 몇 개만; 원시 전체 배열을 모델에 주지 않는다)."""
    candles = svc.get_daily_candles(stock_code, start=start, end=end)
    if not candles:
        return []
    picked = candles if len(candles) <= 6 else candles[:3] + candles[-3:]
    return [
        {
            "trading_day": c.trading_day.isoformat(),
            "close": c.close,
            "volume": c.volume,
            "currency": c.currency,
        }
        for c in picked
    ]
