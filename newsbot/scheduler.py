from __future__ import annotations

from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_EXECUTED
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from newsbot.config import AppConfig
from newsbot.digest import DigestBuilder
from newsbot.pipeline import NewsPipeline


def create_scheduler(config: AppConfig) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone=config.settings.timezone)

    async def ingest_all() -> None:
        await NewsPipeline(config=config).ingest("all")

    async def daily_digest() -> None:
        await DigestBuilder(config=config).build("daily")

    async def weekly_digest() -> None:
        await DigestBuilder(config=config).build("weekly")

    async def send_alerts() -> None:
        await NewsPipeline(config=config).run_alerts()

    def _after_ingest(event) -> None:
        if event.job_id == "ingest_all" and event.exception is None:
            scheduler.add_job(send_alerts, id="send_alerts", replace_existing=True, max_instances=1)

    scheduler.add_listener(_after_ingest, EVENT_JOB_EXECUTED | EVENT_JOB_ERROR)

    scheduler.add_job(ingest_all, "interval", hours=2, id="ingest_all", max_instances=1)
    scheduler.add_job(
        daily_digest,
        CronTrigger(hour=8, minute=30, timezone=config.settings.timezone),
        id="daily_digest",
        max_instances=1,
    )
    scheduler.add_job(
        weekly_digest,
        CronTrigger(day_of_week="sun", hour=18, minute=0, timezone=config.settings.timezone),
        id="weekly_digest",
        max_instances=1,
    )
    return scheduler
