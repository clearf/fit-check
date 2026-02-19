"""
Backfill script: sync historical Garmin activities in 30-day chunks.

Usage:
    python -m fitness.scripts.backfill --days 180

Downloads FIT files + API data for all running activities in the window,
in reverse-chronological order. Respects rate limits with 2s sleep between
activities and 5s between 30-day chunks.

Activities already in the DB are skipped (idempotency via unique constraint).
"""
import argparse
import asyncio
import logging
import time
from datetime import datetime, timedelta

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

CHUNK_DAYS = 30
SLEEP_BETWEEN_ACTIVITIES = 2.0
SLEEP_BETWEEN_CHUNKS = 5.0


async def _backfill(days: int) -> None:
    from fitness.db.engine import get_engine
    from fitness.garmin.client import GarminClient
    from fitness.garmin.sync_service import GarminSyncService
    from sqlmodel import Session, select
    from fitness.models.activity import Activity

    engine = get_engine()

    logger.info("Connecting to Garmin (loading saved session)...")
    client = GarminClient()  # loads session from ~/.fitness/garmin_session/
    await client.connect()
    service = GarminSyncService(client=client, engine=engine)

    end_date = datetime.utcnow()
    start_date = end_date - timedelta(days=days)
    total_synced = 0
    total_skipped = 0

    current_end = end_date
    while current_end > start_date:
        current_start = max(current_end - timedelta(days=CHUNK_DAYS), start_date)
        logger.info(
            "Fetching activities %s → %s",
            current_start.strftime("%Y-%m-%d"),
            current_end.strftime("%Y-%m-%d"),
        )

        # Fetch activities in this window
        page = 0
        while True:
            batch = await client.get_activities(start=page * 20, limit=20)
            if not batch:
                break

            for act_summary in batch:
                start_time_str = act_summary.get("startTimeGMT", "")
                try:
                    act_dt = datetime.strptime(start_time_str, "%Y-%m-%d %H:%M:%S")
                except ValueError:
                    continue

                if act_dt < current_start or act_dt > current_end:
                    continue

                gid = str(act_summary.get("activityId", ""))
                if not gid:
                    continue

                # Check if already synced
                with Session(engine) as s:
                    exists = s.exec(
                        select(Activity).where(Activity.garmin_activity_id == gid)
                    ).first()

                if exists:
                    logger.info("Skipping %s (already in DB)", gid)
                    total_skipped += 1
                    continue

                try:
                    await service.sync_activity(gid)
                    logger.info("Synced %s", gid)
                    total_synced += 1
                except Exception as exc:
                    logger.warning("Failed to sync %s: %s", gid, exc)

                await asyncio.sleep(SLEEP_BETWEEN_ACTIVITIES)

            page += 1
            if len(batch) < 20:
                break

        current_end = current_start
        if current_end > start_date:
            await asyncio.sleep(SLEEP_BETWEEN_CHUNKS)

    logger.info(
        "Backfill complete. Synced: %d, Skipped (already exist): %d",
        total_synced,
        total_skipped,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill Garmin activities")
    parser.add_argument(
        "--days",
        type=int,
        default=180,
        help="Number of days to backfill (default: 180)",
    )
    args = parser.parse_args()
    asyncio.run(_backfill(args.days))


if __name__ == "__main__":
    main()
