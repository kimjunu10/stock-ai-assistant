import logging
from datetime import datetime, timedelta

import pytest

from app.core.config import Settings
from app.jobs.scheduler import NEWS_COLLECTION_JOB_ID, _run_news_stage, build_scheduler


def test_build_scheduler_registers_one_minute_news_job() -> None:
    cfg = Settings(
        news_scheduler_enabled=True,
        news_scheduler_interval_minutes=1,
        news_scheduler_max_per_stock=25,
    )

    scheduler = build_scheduler(cfg)
    job = scheduler.get_job(NEWS_COLLECTION_JOB_ID)

    assert job is not None
    assert job.trigger.interval.total_seconds() == 60
    assert job.max_instances == 1
    assert job.coalesce is True
    assert job.args == (cfg,)
    assert job.next_run_time is not None
    assert job.next_run_time <= datetime.now(job.next_run_time.tzinfo) + timedelta(seconds=1)


def test_build_scheduler_can_be_disabled() -> None:
    cfg = Settings(news_scheduler_enabled=False)

    scheduler = build_scheduler(cfg)

    assert scheduler.get_jobs() == []


def test_news_stage_logs_lifecycle(caplog) -> None:
    with caplog.at_level(logging.INFO, logger="uvicorn.error.news_scheduler"):
        assert _run_news_stage("crawl", lambda: 7) == 7

    assert "NEWS_STAGE_START stage=crawl" in caplog.text
    assert "NEWS_STAGE_DONE stage=crawl" in caplog.text


def test_news_stage_logs_failure_and_reraises(caplog) -> None:
    def fail() -> None:
        raise RuntimeError("database unavailable")

    with caplog.at_level(logging.INFO, logger="uvicorn.error.news_scheduler"):
        with pytest.raises(RuntimeError, match="database unavailable"):
            _run_news_stage("relevance", fail)

    assert "NEWS_STAGE_FAILED stage=relevance" in caplog.text
