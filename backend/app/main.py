"""FastAPI application entry point."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.router import api_router
from app.core.config import settings
from app.jobs.scheduler import NEWS_COLLECTION_JOB_ID, build_scheduler
from app.services.news_sentiment import initialize_news_sentiment_service

logger = logging.getLogger("uvicorn.error.news_scheduler")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Start one scheduler with the API process and stop it cleanly."""

    app.state.news_sentiment = initialize_news_sentiment_service(settings)
    scheduler = build_scheduler(settings)
    app.state.scheduler = scheduler
    if settings.news_scheduler_enabled:
        scheduler.start()
        job = scheduler.get_job(NEWS_COLLECTION_JOB_ID)
        logger.info(
            "News scheduler started interval_minutes=%d next_run_at=%s",
            settings.news_scheduler_interval_minutes,
            job.next_run_time.isoformat() if job and job.next_run_time else None,
        )
    try:
        yield
    finally:
        if scheduler.running:
            scheduler.shutdown(wait=False)
            logger.info("News scheduler stopped")


app = FastAPI(title=settings.app_name, lifespan=lifespan)
app.include_router(api_router, prefix="/api")
