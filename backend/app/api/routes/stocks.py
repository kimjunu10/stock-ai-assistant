"""Stock and stock-home API routes."""

from functools import lru_cache
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from supabase import Client

from app.core.config import settings
from app.db.client import get_supabase_client
from app.schemas.prices import StockCompanyProfile, StockMarketData, StockMarketOverview
from app.sources.prices import SUPPORTED_STOCK_CODES, TossApiError, TossInvestClient

router = APIRouter(prefix="/stocks", tags=["stocks"])


def _market_data_error(exc: TossApiError) -> HTTPException:
    if exc.code == "ip_not_allowed":
        return HTTPException(
            status_code=503,
            detail=(
                "현재 서버 IP가 토스증권 Open API 허용 목록에 없어요. "
                "토스증권 WTS의 설정 > Open API에서 서버 IP를 등록해 주세요."
            ),
        )
    return HTTPException(
        status_code=502,
        detail="토스증권 시세를 불러오지 못했어요. 잠시 후 다시 시도해 주세요.",
    )


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


@router.get("/market-overview", response_model=StockMarketOverview)
def get_stock_market_overview(
    client: Annotated[TossInvestClient, Depends(get_toss_client)],
) -> StockMarketOverview:
    """분석 대상 5개 종목의 실제 현재가를 한 번에 제공한다."""

    try:
        return client.get_stock_market_overview()
    except TossApiError as exc:
        raise _market_data_error(exc) from exc


@router.get("/{stock_code}/market-data", response_model=StockMarketData)
def get_stock_market_data(
    stock_code: str,
    client: Annotated[TossInvestClient, Depends(get_toss_client)],
) -> StockMarketData:
    """실제 현재가, 1분봉·일봉, 호가와 가격 제한을 제공한다."""

    if stock_code not in SUPPORTED_STOCK_CODES:
        raise HTTPException(status_code=404, detail="현재는 지정된 5개 종목만 제공하고 있어요.")

    try:
        return client.get_stock_market_data(stock_code)
    except TossApiError as exc:
        raise _market_data_error(exc) from exc


@router.get("/{stock_code}/company-profile", response_model=StockCompanyProfile)
def get_stock_company_profile(
    stock_code: str,
    client: Annotated[TossInvestClient, Depends(get_toss_client)],
    db: Annotated[Client, Depends(get_supabase_client)],
) -> StockCompanyProfile:
    """DART 기업개황과 토스 종목 마스터의 회사 기본 정보를 제공한다."""

    if stock_code not in SUPPORTED_STOCK_CODES:
        raise HTTPException(status_code=404, detail="현재는 지정된 5개 종목만 제공하고 있어요.")
    response = (
        db.table("company_profiles")
        .select("stock_name,corp_name_eng,ceo_nm,est_dt,hm_url,induty_code")
        .eq("stock_code", stock_code)
        .limit(1)
        .execute()
    )
    dart_profile = (response.data or [None])[0]
    try:
        return client.get_stock_info(stock_code, dart_profile=dart_profile)
    except TossApiError as exc:
        raise _market_data_error(exc) from exc
