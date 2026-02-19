"""Sync trigger and status routes."""
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from fitness.db.engine import get_engine, get_session
from fitness.garmin.client import GarminClient
from fitness.garmin.sync_service import GarminSyncService
from fitness.models.activity import Activity
from fitness.models.sync import SyncLog

router = APIRouter()


class SyncTriggerRequest(BaseModel):
    activity_id: Optional[str] = None  # If None, syncs the most recent activity


class SyncStatusResponse(BaseModel):
    status: str
    started_at: Optional[datetime]
    finished_at: Optional[datetime]
    activities_synced: Optional[int]
    error_message: Optional[str]


async def _do_sync(activity_id: Optional[str] = None) -> None:
    """Background task: load saved session and sync."""
    engine = get_engine()
    client = GarminClient()  # loads session from ~/.fitness/garmin_session/
    await client.connect()
    service = GarminSyncService(client=client, engine=engine)

    if activity_id:
        await service.sync_activity(activity_id)
    else:
        # Sync most recent running activity
        activities = await client.get_activities(start=0, limit=1)
        if activities:
            gid = str(activities[0].get("activityId", ""))
            await service.sync_activity(gid)


@router.post("/trigger")
async def trigger_sync(
    request: SyncTriggerRequest,
    background_tasks: BackgroundTasks,
):
    """
    Trigger an on-demand Garmin sync (called from iOS Shortcut).
    Returns immediately; sync runs in background.
    """
    background_tasks.add_task(_do_sync, request.activity_id)
    return {"message": "Sync started", "activity_id": request.activity_id}


@router.get("/status", response_model=SyncStatusResponse)
def sync_status(session: Session = Depends(get_session)):
    """Return the status of the most recent sync job."""
    log = session.exec(
        select(SyncLog).order_by(SyncLog.started_at.desc())
    ).first()
    if not log:
        return SyncStatusResponse(
            status="never_run",
            started_at=None,
            finished_at=None,
            activities_synced=None,
            error_message=None,
        )
    return SyncStatusResponse(
        status=log.status,
        started_at=log.started_at,
        finished_at=log.finished_at,
        activities_synced=log.activities_synced,
        error_message=log.error_message,
    )


@router.get("/latest", response_model=Optional[Activity])
def latest_activity(session: Session = Depends(get_session)):
    """Return the most recently synced activity."""
    activity = session.exec(
        select(Activity).order_by(Activity.start_time_utc.desc())
    ).first()
    return activity
