"""
RunReport assembler.

Queries the DB for a single activity and all associated data, then runs
the analysis algorithms to produce a RunReport — the single object consumed
by the prompt layer to generate Claude's debrief.

All analysis is pure (no DB access inside the algorithm modules).
"""
from dataclasses import dataclass, field
from datetime import date
from typing import List, Optional

from sqlmodel import Session, select

from fitness.analysis.bonk import BonkEvent, detect_bonk
from fitness.analysis.galloway import GallowaySegments, detect_galloway_segments
from fitness.analysis.heart_rate import CardiacDriftEvent, detect_cardiac_drift
from fitness.analysis.segments import RunSegment, build_mile_segments
from fitness.analysis.timeseries import TimeseriesPoint, datapoints_to_timeseries
from fitness.models.activity import Activity, ActivityDatapoint, ActivitySplit
from fitness.models.wellness import BodyBatteryRecord, HRVRecord, SleepRecord


@dataclass
class RunReport:
    """
    Complete data package for one run.

    Produced by build_run_report() and consumed by the prompt layer.
    """
    activity: Activity
    timeseries: List[TimeseriesPoint]
    mile_segments: List[RunSegment]
    bonk_events: List[BonkEvent]
    cardiac_drift: Optional[CardiacDriftEvent]
    galloway: GallowaySegments

    # Previous-night wellness context (None if not synced)
    sleep: Optional[SleepRecord] = None
    hrv: Optional[HRVRecord] = None
    body_battery: Optional[BodyBatteryRecord] = None


def build_run_report(activity_id: int, engine) -> RunReport:
    """
    Assemble a RunReport for the given activity ID.

    Args:
        activity_id: Primary key of the Activity row.
        engine: SQLAlchemy engine.

    Returns:
        RunReport with all analysis computed.

    Raises:
        ValueError: If no activity with the given ID exists.
    """
    with Session(engine) as s:
        # ── Fetch activity ────────────────────────────────────────────────────
        activity = s.get(Activity, activity_id)
        if activity is None:
            raise ValueError(f"No activity found with id={activity_id}")

        # ── Fetch datapoints ──────────────────────────────────────────────────
        raw_datapoints = s.exec(
            select(ActivityDatapoint)
            .where(ActivityDatapoint.activity_id == activity_id)
            .order_by(ActivityDatapoint.elapsed_seconds)
        ).all()

        # Convert to dict list for datapoints_to_timeseries
        dp_dicts = [
            {
                "elapsed_seconds": dp.elapsed_seconds,
                "heart_rate": dp.heart_rate,
                "speed_ms": dp.speed_ms,
                "pace_seconds_per_km": dp.pace_seconds_per_km,
                "elevation_meters": dp.elevation_meters,
                "cadence_spm": dp.cadence_spm,
                "distance_meters": dp.distance_meters,
                "lat": dp.lat,
                "lon": dp.lon,
                "temperature_c": dp.temperature_c,
            }
            for dp in raw_datapoints
        ]

        # ── Fetch splits ──────────────────────────────────────────────────────
        splits = s.exec(
            select(ActivitySplit)
            .where(ActivitySplit.activity_id == activity_id)
            .order_by(ActivitySplit.split_index)
        ).all()

        # ── Fetch wellness for the run date (previous night's sleep) ─────────
        run_date: date = activity.start_time_utc.date()
        prev_date = date.fromordinal(run_date.toordinal() - 1)

        sleep = s.exec(
            select(SleepRecord).where(SleepRecord.sleep_date == prev_date)
        ).first()

        hrv = s.exec(
            select(HRVRecord).where(HRVRecord.record_date == run_date)
        ).first()

        body_battery = s.exec(
            select(BodyBatteryRecord).where(BodyBatteryRecord.record_date == run_date)
        ).first()

    # ── Build timeseries ──────────────────────────────────────────────────────
    timeseries = datapoints_to_timeseries(dp_dicts)

    # ── Run analysis algorithms ───────────────────────────────────────────────
    mile_segments = build_mile_segments(timeseries)
    bonk_events = detect_bonk(timeseries)
    cardiac_drift = detect_cardiac_drift(timeseries)

    # Galloway detection from typed splits (convert ActivitySplit → dict list)
    split_dicts = [
        {
            "splitType": sp.split_type.replace("_segment", "").upper(),
            "totalElapsedTime": sp.duration_seconds,
            "totalDistance": sp.distance_meters,
            "averageHR": sp.avg_hr,
            "averageSpeed": (1000.0 / sp.avg_pace_seconds_per_km)
            if sp.avg_pace_seconds_per_km
            else None,
            "startTime": sp.start_elapsed_seconds,
        }
        for sp in splits
    ]
    galloway = detect_galloway_segments(split_dicts)

    return RunReport(
        activity=activity,
        timeseries=timeseries,
        mile_segments=mile_segments,
        bonk_events=bonk_events,
        cardiac_drift=cardiac_drift,
        galloway=galloway,
        sleep=sleep,
        hrv=hrv,
        body_battery=body_battery,
    )
