"""Stock and stock-home API routes."""

from functools import lru_cache
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from app.core.config import settings
from app.schemas.prices import StockMarketData
from app.sources.prices import SUPPORTED_STOCK_CODES, TossApiError, TossInvestClient

router = APIRouter(prefix="/stocks", tags=["stocks"])


@lru_cache(maxsize=1)
def get_toss_client() -> TossInvestClient:
    """프로세스에서 OAuth 토큰과 시세 캐시를 공유하는 클라이언트를 반환한다."""

    settings.validate_toss_market_data()
    return TossInvestClient(
        settings.toss_client_id,
        settings.toss_client_secret,
        timeout_seconds=settings.toss_request_timeout_seconds,
        market_data_cache_seconds=settings.toss_market_data_cache_seconds,
    )


@router.get("/{stock_code}/market-data", response_model=StockMarketData)
def get_stock_market_data(
    stock_code: str,
    client: Annotated[TossInvestClient, Depends(get_toss_client)],
) -> StockMarketData:
    """지정된 5개 종목의 실제 원화 현재가와 최근 6개월 수정 일봉을 제공한다."""

    if stock_code not in SUPPORTED_STOCK_CODES:
        raise HTTPException(status_code=404, detail="현재는 지정된 5개 종목만 제공하고 있어요.")

    try:
        return client.get_stock_market_data(stock_code)
    except TossApiError as exc:
        raise HTTPException(
            status_code=502,
            detail="토스증권 시세를 불러오지 못했어요. 잠시 후 다시 시도해 주세요.",
        ) from exc
