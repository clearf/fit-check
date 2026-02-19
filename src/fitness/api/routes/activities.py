"""Activity query routes."""
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from fitness.db.engine import get_session
from fitness.models.activity import Activity

router = APIRouter()


@router.get("/", response_model=List[Activity])
def list_activities(
    limit: int = 20,
    offset: int = 0,
    session: Session = Depends(get_session),
):
    """List recent activities, newest first."""
    activities = session.exec(
        select(Activity)
        .order_by(Activity.start_time_utc.desc())
        .offset(offset)
        .limit(limit)
    ).all()
    return activities


@router.get("/{activity_id}", response_model=Activity)
def get_activity(activity_id: int, session: Session = Depends(get_session)):
    """Fetch a single activity by primary key."""
    activity = session.get(Activity, activity_id)
    if not activity:
        raise HTTPException(status_code=404, detail="Activity not found")
    return activity


@router.get("/garmin/{garmin_id}", response_model=Activity)
def get_activity_by_garmin_id(
    garmin_id: str, session: Session = Depends(get_session)
):
    """Fetch activity by Garmin activity ID string."""
    activity = session.exec(
        select(Activity).where(Activity.garmin_activity_id == garmin_id)
    ).first()
    if not activity:
        raise HTTPException(status_code=404, detail="Activity not found")
    return activity
