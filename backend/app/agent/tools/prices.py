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
from typing import Literal

from pydantic import BaseModel, Field

from app.agent.tools.common import (
    SourceRef,
    ToolResult,
    error,
    log_tool_exception,
    no_data,
    ok,
    sanitize_exception,
)
from app.services.stock_prices import (
    EventWindowReturn,
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


def normalize_price_lookback(value: str | None) -> str | None:
    """모델의 1일 표현을 현재가 계약으로 정규화하고 허용 기간만 통과시킨다."""

    normalized = (value or "").strip().lower()
    if normalized in {"", "1d"}:
        return None
    if normalized not in LOOKBACK_DAYS:
        raise ValueError(f"지원하지 않는 기간입니다: {value}")
    return normalized


class GetStockPricesInput(BaseModel):
    stock_code: str = Field(pattern=r"^[0-9]{6}$")
    # 기간 미지정 → 현재가만. lookback 지정 → 기간 수익률+시작/종료 거래일.
    lookback: Literal["1w", "2w", "1m", "3m", "6m", "1y"] | None = None
    start_date: str | None = None  # YYYY-MM-DD (명시 구간)
    end_date: str | None = None  # YYYY-MM-DD
    include_daily: bool = False  # 일봉 목록 포함 여부(기본 미포함, 요약만)


class CalculateEventReturnInput(BaseModel):
    """사건 전후 수익률 입력.

    event_date 는 필수다. 사건을 특정하지 못한 상태에서 일반 기간 수익률로 대체하는 것을
    입력 계약 수준에서 차단한다(과거 결함: event_date 누락 → 최근 1개월 수익률 반환).
    일반 기간 수익률이 필요하면 get_stock_prices(lookback=...)를 쓴다.
    """

    stock_code: str = Field(pattern=r"^[0-9]{6}$")
    # 사건 기준일(뉴스·공시 발표일). 필수 — 없으면 이 Tool 을 호출할 수 없다.
    event_date: str  # YYYY-MM-DD
    # 사건 식별자·출처(근거 추적용). 사건 문맥에서 전달된 값을 그대로 싣는다.
    event_id: str | None = None
    window: str = "5d"  # EVENT_WINDOWS 키(대칭 ±N거래일 보조 결과)


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
        stock_code=stock_code,
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
        "end_price_kind": r.end_price_kind,
        "unit": "원",
    }


def run_get_stock_prices(svc: StockPriceService, inp: GetStockPricesInput) -> ToolResult:
    """현재가 또는 지정 기간 가격을 반환한다(수익률은 서비스가 계산)."""
    try:
        # (1) 명시 구간(start/end) → 기간 수익률 + 선택적 일봉.
        start = _parse_date(inp.start_date)
        end = _parse_date(inp.end_date)
        if start and end:
            q = svc.get_current_quote(inp.stock_code)
            live_quote = q if q is not None and start <= q.trading_day <= end else None
            r = svc.get_period_return(
                inp.stock_code,
                start=start,
                end=end,
                live_quote=live_quote,
                start_on_or_before=True,
            )
            if r is None:
                return no_data(
                    f"{inp.stock_code} {start}~{end} 구간의 거래일 데이터가 없습니다. "
                    "다른 기간으로 대체하지 않았습니다."
                )
            data = {
                "quote": _quote_payload(live_quote) if live_quote is not None else None,
                "period": _return_payload(r),
            }
            sources = [
                _price_source(
                    inp.stock_code,
                    trading_day=r.end_trading_day,
                    as_of=r.end_trading_day.isoformat(),
                    extra={"start": r.start_trading_day.isoformat(), "adjusted": r.adjusted},
                )
            ]
            # 기간 비교는 질문에 "그래프"라는 단어가 없어도 해당 구간 자체가 시각화 범위다.
            data.update(
                _daily_payload(
                    svc,
                    inp.stock_code,
                    r.start_trading_day,
                    r.end_trading_day,
                    live_quote=live_quote,
                )
            )
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
            r = svc.get_period_return(
                inp.stock_code,
                start=start,
                end=q.trading_day,
                live_quote=q,
            )
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
        if inp.lookback:
            data.update(
                _daily_payload(
                    svc,
                    inp.stock_code,
                    q.trading_day - timedelta(days=LOOKBACK_DAYS[inp.lookback]),
                    q.trading_day,
                    live_quote=q,
                )
            )
        else:
            # 현재가·전일 대비 질문은 고정 6개월 차트 대신 직전 확정 종가→현재가만 그린다.
            data.update(_quote_comparison_payload(svc, inp.stock_code, q))
        return ok(data, sources=sources)

    except StockPriceError as e:
        log_tool_exception(e, layer="StockPriceService.get_stock_prices")
        return error(str(e))
    except TossApiError as e:
        if getattr(e, "code", "") == "stock_not_found":
            return no_data(f"{inp.stock_code} 종목을 찾을 수 없습니다.")
        log_tool_exception(e, layer="TossStockApi.get_stock_prices")
        return error(sanitize_exception(e))
    except Exception as e:  # noqa: BLE001
        log_tool_exception(e, layer="StockPriceService.get_stock_prices")
        return error(sanitize_exception(e))


def run_calculate_event_return(
    svc: StockPriceService, inp: CalculateEventReturnInput
) -> ToolResult:
    """사건 발표 전후 주가를 반환한다(백엔드 계산).

    계약(§5): 발표 전 마지막 확정 거래일 종가를 기준으로, 발표 후 1·3·5거래일 종가·수익률을
    반환한다. 발표 이후 확정 거래일이 하나도 없으면 no_data 이며, 다른 기간(최근 1개월 등)
    으로 절대 대체하지 않는다.
    """
    try:
        event_date = _parse_date(inp.event_date)
        if event_date is None:
            return error("event_date 형식이 올바르지 않습니다(YYYY-MM-DD).")
        if inp.window not in EVENT_WINDOWS:
            return error(f"지원하지 않는 window 입니다: {inp.window}")

        ew = svc.get_event_window_return(
            inp.stock_code,
            event_date=event_date,
            horizons=StockPriceService.DEFAULT_EVENT_HORIZONS,
        )
        if ew is None:
            return no_data(
                f"{inp.stock_code} {event_date.isoformat()} 기준 발표 전 확정 거래일 데이터를 "
                "찾을 수 없습니다. 다른 기간으로 대체하지 않았습니다."
            )
        if not ew.has_post_data:
            # 발표 이후 확정 거래일 미존재 — 데이터 부족 상태를 그대로 반환한다.
            return no_data(
                f"{inp.stock_code} {event_date.isoformat()} 발표 이후 확정 거래일 데이터가 "
                "아직 없어 계산할 수 없습니다. 다른 기간으로 대체하지 않았습니다.",
                data={
                    "stock_code": inp.stock_code,
                    "event_id": inp.event_id,
                    "event_date": event_date.isoformat(),
                    "basis": "event",
                    "baseline_trading_day": ew.baseline_trading_day.isoformat(),
                    "baseline_close": ew.baseline_close,
                    "horizons": [],
                    "has_post_data": False,
                },
            )
        return _event_window_ok(inp, ew)

    except StockPriceError as e:
        log_tool_exception(e, layer="StockPriceService.get_event_window_return")
        return error(str(e))
    except TossApiError as e:
        if getattr(e, "code", "") == "stock_not_found":
            return no_data(f"{inp.stock_code} 종목을 찾을 수 없습니다.")
        log_tool_exception(e, layer="TossStockApi.get_event_window_return")
        return error(sanitize_exception(e))
    except Exception as e:  # noqa: BLE001
        log_tool_exception(e, layer="StockPriceService.get_event_window_return")
        return error(sanitize_exception(e))


def _event_window_ok(inp: CalculateEventReturnInput, ew: EventWindowReturn) -> ToolResult:
    """사건 전후 결과를 계약 형태로 직렬화한다(수익률은 서비스 계산값 그대로)."""
    last = ew.horizons[-1]
    data = {
        "stock_code": ew.stock_code,
        "event_id": inp.event_id,
        "event_date": ew.event_date.isoformat(),
        "basis": "event",  # 일반 기간이 아니라 사건 기준임을 명시
        "baseline_trading_day": ew.baseline_trading_day.isoformat(),
        "baseline_close": ew.baseline_close,
        "has_post_data": True,
        "horizons": [
            {
                "horizon_days": h.horizon_days,
                "trading_day": h.trading_day.isoformat(),
                "close": h.close,
                "change": h.change,
                "return_pct": h.return_pct,
            }
            for h in ew.horizons
        ],
        # 발표 전 기준 거래일부터 마지막 관측 지평까지의 실제 OHLCV.
        # 모델은 horizons를 사용하고, UI는 이 값을 캔들 차트로 그린다.
        "daily_full": [_candle_point(c) for c in ew.daily],
        # 실제 사용한 시작·종료 거래일(계약 필수 항목).
        "start_trading_day": ew.baseline_trading_day.isoformat(),
        "end_trading_day": last.trading_day.isoformat(),
        "start_close": ew.baseline_close,
        "end_close": last.close,
        "change": last.change,
        "return_pct": last.return_pct,
        "currency": ew.currency,
        "adjusted": ew.adjusted,
        "unit": "원",
        # 인과 아님(시간적 관계만).
        "note": (
            f"{ew.event_date.isoformat()} 발표 전 마지막 거래일"
            f"({ew.baseline_trading_day.isoformat()}) 종가 기준, 발표 후 "
            + "·".join(f"{h.horizon_days}거래일" for h in ew.horizons)
        ),
    }
    sources = [
        _price_source(
            ew.stock_code,
            trading_day=ew.baseline_trading_day,
            as_of=ew.baseline_trading_day.isoformat(),
            extra={"kind": "event_baseline", "adjusted": ew.adjusted},
        )
    ]
    sources.extend(
        _price_source(
            ew.stock_code,
            trading_day=h.trading_day,
            as_of=h.trading_day.isoformat(),
            extra={
                "kind": "event_horizon",
                "horizon_days": h.horizon_days,
                "adjusted": ew.adjusted,
            },
        )
        for h in ew.horizons
    )
    return ok(data, sources=sources)


# UI 주가 선그래프 상한. 긴 기간은 끝부분만 자르지 않고 전체 구간에서 실제 거래일을
# 균등 선택해 시작·종료 범위를 보존한다.
_UI_DAILY_MAX = 60


def _candle_point(c) -> dict:
    return {
        "trading_day": c.trading_day.isoformat(),
        "open": c.open,
        "high": c.high,
        "low": c.low,
        "close": c.close,
        "volume": c.volume,
        "currency": c.currency,
    }


def _sample_points(points: list[dict], limit: int = _UI_DAILY_MAX) -> tuple[list[dict], bool]:
    if len(points) <= limit:
        return points, False
    last_index = len(points) - 1
    indices = sorted({round(i * last_index / (limit - 1)) for i in range(limit)})
    return [points[index] for index in indices], True


def _daily_payload(
    svc: StockPriceService,
    stock_code: str,
    start: date,
    end: date,
    *,
    live_quote: PriceQuote | None = None,
) -> dict:
    """일봉을 모델용 요약과 UI용 전체(상한)로 나눠 반환한다.

    - daily: 모델 문맥에 넣는 작은 요약(앞3+뒤3). Agent Tool 선택·답변 문맥을 키우지 않음.
    - daily_full: UI 선그래프 전용. 요청 구간의 시작·종료를 보존하며 실제 거래일
      포인트를 최대 60개로 균등 표본화한다. 프런트는 값을 다시 계산하지 않고
      이 점들을 그대로 그린다. 200개 API 상한·캐시는
      StockPriceService(get_daily_candles)가 이미 처리한다.
    """
    candles = svc.get_daily_candles(stock_code, start=start, end=end)
    points = [_candle_point(c) for c in candles]
    if live_quote is not None and start <= live_quote.trading_day <= end:
        # 당일 일봉은 장중 집계값이거나 제공자별 세션 차이가 있을 수 있다. 동일 날짜를
        # 단일종목 현재가로 교체해 숫자 카드·답변·차트의 마지막 값이 항상 일치하게 한다.
        live_day = live_quote.trading_day.isoformat()
        existing = next((point for point in points if point["trading_day"] == live_day), None)
        points = [point for point in points if point["trading_day"] != live_day]
        live_point = {
            **(existing or {}),
            "trading_day": live_day,
            "close": live_quote.price,
            "volume": existing.get("volume") if existing else None,
            "currency": live_quote.currency,
            "price_kind": "current",
            "as_of": live_quote.as_of.isoformat(),
        }
        if existing and existing.get("high", 0) > 0 and existing.get("low", 0) > 0:
            live_point["high"] = max(existing["high"], live_quote.price)
            live_point["low"] = min(existing["low"], live_quote.price)
        points.append(live_point)
        points.sort(key=lambda point: point["trading_day"])
    if not points:
        return {"daily": [], "daily_full": []}
    # 일봉을 이용한 모든 후속 분석(하락일, 상승일, 변동 폭 등)에 공통으로 쓸 수 있도록
    # 인접 거래일 변화량을 서버에서 계산한다. 특정 질문 문구나 상승/하락 조건을
    # 하드코딩하지 않고, 모델이 검증된 파생값을 선택해 설명하게 한다.
    for index in range(1, len(points)):
        previous_close = points[index - 1].get("close")
        current_close = points[index].get("close")
        if not isinstance(previous_close, (int, float)) or not isinstance(
            current_close, (int, float)
        ):
            continue
        change = current_close - previous_close
        points[index]["previous_close"] = previous_close
        points[index]["change"] = round(change, 4)
        points[index]["change_rate_pct"] = (
            round(change / previous_close * 100, 4) if previous_close else None
        )
    summary = points if len(points) <= 6 else points[:3] + points[-3:]
    ui, sampled = _sample_points(points)
    return {
        "daily": summary,
        "daily_full": ui,
        "daily_full_sampled": sampled,
    }


def _quote_comparison_payload(
    svc: StockPriceService,
    stock_code: str,
    quote: PriceQuote,
) -> dict:
    """전일 대비 질문용: 직전 확정 거래일 종가와 현재가 두 점만 반환한다."""

    candles = svc.get_daily_candles(
        stock_code,
        start=quote.trading_day - timedelta(days=10),
        end=quote.trading_day,
    )
    previous = [c for c in candles if c.trading_day < quote.trading_day]
    if not previous:
        return {"daily": [], "daily_full": []}
    point = max(previous, key=lambda candle: candle.trading_day)
    current = next((c for c in candles if c.trading_day == quote.trading_day), None)
    live = {
        **(_candle_point(current) if current else {}),
        "trading_day": quote.trading_day.isoformat(),
        "close": quote.price,
        "volume": current.volume if current else None,
        "currency": quote.currency,
        "price_kind": "current",
        "as_of": quote.as_of.isoformat(),
    }
    if current and current.high > 0 and current.low > 0:
        live["high"] = max(current.high, quote.price)
        live["low"] = min(current.low, quote.price)
    previous_point = {
        **_candle_point(point),
        # 전일 비교 기준은 일봉 closePrice가 아니라 현재가와 함께 제공된 basePrice다.
        "close": quote.previous_close,
        "currency": quote.currency,
        "price_kind": "previous_close",
    }
    if point.high > 0 and point.low > 0:
        previous_point["high"] = max(point.high, quote.previous_close)
        previous_point["low"] = min(point.low, quote.previous_close)
    points = [previous_point, live]
    return {"daily": points, "daily_full": points, "daily_full_sampled": False}
