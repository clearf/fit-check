"""
APScheduler jobs for background sync.

Nightly sync at 3am catches anything missed by the on-demand webhook
(e.g., if the iOS Shortcut wasn't triggered, or the watch synced late).

The scheduler runs inside the same process as the bot (wired in main.py).
"""
import asyncio
import logging
from datetime import datetime, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from fitness.config import get_settings

logger = logging.getLogger(__name__)


def build_scheduler(engine) -> AsyncIOScheduler:
    """
    Create and configure the APScheduler.

    Args:
        engine: SQLAlchemy engine to pass to the sync service.

    Returns:
        Configured AsyncIOScheduler (not yet started).
    """
    settings = get_settings()
    scheduler = AsyncIOScheduler()

    scheduler.add_job(
        _nightly_sync,
        trigger="cron",
        hour=settings.garmin_sync_hour,
        minute=0,
        id="nightly_sync",
        replace_existing=True,
        kwargs={"engine": engine},
    )

    return scheduler


async def _nightly_sync(engine) -> None:
    """
    Nightly job: sync the most recent activity from Garmin.

    Idempotent — safe to run if already synced today.
    """
    from fitness.garmin.client import GarminClient
    from fitness.garmin.sync_service import GarminSyncService

    settings = get_settings()
    logger.info("Nightly sync starting at %s", datetime.utcnow().isoformat())

    try:
        client = GarminClient(settings.garmin_email, settings.garmin_password)
        await client.connect()
        service = GarminSyncService(client=client, engine=engine)

        # Sync up to 3 most recent activities (catches late syncs from prior days)
        activities = await client.get_activities(start=0, limit=3)
        for act_summary in activities:
            gid = str(act_summary.get("activityId", ""))
            if gid:
                await service.sync_activity(gid)
                logger.info("Synced activity %s", gid)

    except Exception as exc:
        logger.error("Nightly sync failed: %s", exc)
