"""Top-level API router composition."""

from fastapi import APIRouter

from app.api.routes import clusters, disclosures, financials, qa, reports, stocks

api_router = APIRouter()
api_router.include_router(stocks.router)
api_router.include_router(clusters.router)
api_router.include_router(disclosures.router)
api_router.include_router(financials.router)
api_router.include_router(reports.router)
api_router.include_router(qa.router)
