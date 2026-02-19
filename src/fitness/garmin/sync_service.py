"""
GarminSyncService — orchestrates fetching data from Garmin and persisting to DB.

Flow for a single activity sync:
  1. Create SyncLog (status="running")
  2. Fetch activity summary from API → normalize → upsert Activity row
  3. Fetch FIT datapoints → upsert ActivityDatapoint rows
  4. Fetch typed splits → normalize → upsert ActivitySplit rows
  5. Update SyncLog (status="success")

On any exception: update SyncLog (status="error") and re-raise.

Idempotency: uses garmin_activity_id unique constraint. On conflict, the
existing Activity row is reused and its child rows (datapoints, splits) are
deleted and re-inserted so stale data is never left behind.
"""
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlmodel import Session, select

from fitness.garmin.normalizer import (
    normalize_activity_summary,
    normalize_typed_split,
)
from fitness.models.activity import Activity, ActivityDatapoint, ActivitySplit
from fitness.models.sync import SyncLog


class GarminSyncService:
    """Orchestrates Garmin → DB sync for one or more activities."""

    def __init__(self, client, engine):
        """
        Args:
            client: GarminClient instance (or AsyncMock in tests).
            engine: SQLAlchemy engine (SQLModel create_engine result).
        """
        self.client = client
        self.engine = engine

    async def sync_activity(self, activity_id: str) -> Activity:
        """
        Fetch and persist all data for a single Garmin activity.

        Args:
            activity_id: Garmin activity ID as a string.

        Returns:
            The persisted Activity row.

        Raises:
            Any exception from the Garmin client (after recording error log).
        """
        log = self._create_sync_log()

        try:
            activity = await self._upsert_activity(activity_id)
            await self._upsert_datapoints(activity)
            await self._upsert_splits(activity)
            self._finish_sync_log(log, status="success", activities_synced=1)
            return activity

        except Exception as exc:
            self._finish_sync_log(
                log, status="error", error_message=str(exc)
            )
            raise

    # ─── Internal helpers ─────────────────────────────────────────────────────

    def _create_sync_log(self) -> SyncLog:
        log = SyncLog(started_at=datetime.utcnow(), status="running")
        with Session(self.engine) as s:
            s.add(log)
            s.commit()
            s.refresh(log)
        return log

    def _finish_sync_log(
        self,
        log: SyncLog,
        *,
        status: str,
        activities_synced: int = 0,
        error_message: Optional[str] = None,
    ) -> None:
        with Session(self.engine) as s:
            db_log = s.get(SyncLog, log.id)
            db_log.status = status
            db_log.finished_at = datetime.utcnow()
            db_log.activities_synced = activities_synced
            db_log.error_message = error_message
            s.add(db_log)
            s.commit()

    async def _upsert_activity(self, activity_id: str) -> Activity:
        """Fetch summary and upsert Activity row. Returns the Activity."""
        raw = await self.client.get_activity_summary(activity_id)
        fields = normalize_activity_summary(raw)

        with Session(self.engine) as s:
            existing = s.exec(
                select(Activity).where(
                    Activity.garmin_activity_id == fields["garmin_activity_id"]
                )
            ).first()

            if existing:
                # Update scalar fields in-place (keeps same id)
                for k, v in fields.items():
                    setattr(existing, k, v)
                existing.synced_at = datetime.utcnow()
                s.add(existing)
                s.commit()
                s.refresh(existing)
                return existing
            else:
                activity = Activity(**fields)
                s.add(activity)
                s.commit()
                s.refresh(activity)
                return activity

    async def _upsert_datapoints(self, activity: Activity) -> None:
        """Download FIT file, parse datapoints, delete old rows, insert fresh."""
        raw_points = await self.client.get_fit_datapoints(
            activity.garmin_activity_id
        )

        with Session(self.engine) as s:
            # Delete existing datapoints for this activity (idempotency)
            existing = s.exec(
                select(ActivityDatapoint).where(
                    ActivityDatapoint.activity_id == activity.id
                )
            ).all()
            for dp in existing:
                s.delete(dp)
            s.flush()

            # Insert fresh
            for pt in raw_points:
                dp = ActivityDatapoint(
                    activity_id=activity.id,
                    user_id=activity.user_id,
                    elapsed_seconds=int(pt.get("elapsed_seconds", 0)),
                    heart_rate=pt.get("heart_rate"),
                    speed_ms=pt.get("speed_ms"),
                    pace_seconds_per_km=pt.get("pace_seconds_per_km"),
                    elevation_meters=pt.get("elevation_meters"),
                    cadence_spm=pt.get("cadence_spm"),
                    distance_meters=pt.get("distance_meters"),
                    lat=pt.get("lat"),
                    lon=pt.get("lon"),
                    temperature_c=pt.get("temperature_c"),
                )
                s.add(dp)
            s.commit()

    async def _upsert_splits(self, activity: Activity) -> None:
        """Fetch typed splits, normalize, delete old rows, insert fresh."""
        raw_splits = await self.client.get_activity_typed_splits(
            activity.garmin_activity_id
        )

        with Session(self.engine) as s:
            # Delete existing splits
            existing = s.exec(
                select(ActivitySplit).where(
                    ActivitySplit.activity_id == activity.id
                )
            ).all()
            for sp in existing:
                s.delete(sp)
            s.flush()

            # Insert normalized splits
            for i, raw in enumerate(raw_splits):
                fields = normalize_typed_split(raw, split_index=i)
                split = ActivitySplit(
                    activity_id=activity.id,
                    user_id=activity.user_id,
                    **fields,
                )
                s.add(split)
            s.commit()
