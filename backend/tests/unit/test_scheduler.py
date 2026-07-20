from app.core.config import Settings
from app.jobs.scheduler import NEWS_COLLECTION_JOB_ID, build_scheduler


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


def test_build_scheduler_can_be_disabled() -> None:
    cfg = Settings(news_scheduler_enabled=False)

    scheduler = build_scheduler(cfg)

    assert scheduler.get_jobs() == []
