from __future__ import annotations

import logging
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_EXECUTED
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from newsbot.config import AppConfig
from newsbot.digest import DigestBuilder
from newsbot.pipeline import NewsPipeline

logger = logging.getLogger("newsbot.scheduler")


def _configure_logging() -> None:
    """Send scheduler + APScheduler job logs to the terminal (INFO)."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    for name in ("newsbot.scheduler", "apscheduler"):
        log = logging.getLogger(name)
        log.setLevel(logging.INFO)
        if not any(isinstance(h, logging.StreamHandler) for h in log.handlers):
            log.addHandler(handler)
        log.propagate = False


def create_scheduler(config: AppConfig) -> AsyncIOScheduler:
    _configure_logging()
    timezone = ZoneInfo(config.settings.timezone)
    scheduler = AsyncIOScheduler(timezone=config.settings.timezone)

    async def ingest_all() -> None:
        logger.info("ingest_all: starting")
        report = await NewsPipeline(config=config).ingest("all")
        logger.info(
            "ingest_all: collected=%d extracted=%d clustered=%d alerts_queued=%d",
            report.collected,
            report.extracted,
            report.clustered,
            report.alerts_queued,
        )

    async def daily_digest() -> None:
        logger.info("daily_digest: building")
        digest_id = await DigestBuilder(config=config).build("daily")
        logger.info("daily_digest: saved %s", digest_id)

    async def weekly_digest() -> None:
        logger.info("weekly_digest: building")
        digest_id = await DigestBuilder(config=config).build("weekly")
        logger.info("weekly_digest: saved %s", digest_id)

    async def send_alerts() -> None:
        logger.info("send_alerts: starting")
        sent, failed = await NewsPipeline(config=config).run_alerts()
        logger.info("send_alerts: sent=%d failed=%d", sent, failed)

    def _after_ingest(event) -> None:
        if event.job_id != "ingest_all":
            return
        if event.exception is not None:
            logger.warning("ingest_all failed; skipping send_alerts: %s", event.exception)
            return
        logger.info("ingest_all complete -> queuing send_alerts")
        scheduler.add_job(send_alerts, id="send_alerts", replace_existing=True, max_instances=1)

    scheduler.add_listener(_after_ingest, EVENT_JOB_EXECUTED | EVENT_JOB_ERROR)

    # Run an ingest immediately at startup, then every 5 minutes. misfire_grace_time gives the
    # first (startup) run slack so a slow boot doesn't cause it to be skipped.
    scheduler.add_job(
        ingest_all,
        "interval",
        minutes=5,
        id="ingest_all",
        max_instances=1,
        next_run_time=datetime.now(timezone),
        misfire_grace_time=60,
    )
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
