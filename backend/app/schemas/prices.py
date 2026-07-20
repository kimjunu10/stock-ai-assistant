"""종목 현재가와 캔들 API 응답 모델."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict


def _to_camel(value: str) -> str:
    head, *tail = value.split("_")
    return head + "".join(part.capitalize() for part in tail)


class CamelModel(BaseModel):
    """내부는 snake_case, JSON 응답은 camelCase로 직렬화한다."""

    model_config = ConfigDict(alias_generator=_to_camel, populate_by_name=True)


class Candle(CamelModel):
    time: str
    open: float
    high: float
    low: float
    close: float
    volume: int


class StockQuote(CamelModel):
    price: float
    previous_close: float
    change: float
    change_rate: float
    currency: str
    as_of: datetime
    volume: int


class StockMarketData(CamelModel):
    stock_code: str
    interval: str
    period: str
    adjusted: bool
    source: str
    quote: StockQuote
    candles: list[Candle]
