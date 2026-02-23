"""Tests for RunReport assembler."""
from datetime import date, datetime
from pathlib import Path
from typing import List

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from fitness.models.activity import Activity, ActivityDatapoint, ActivitySplit
from fitness.models.wellness import SleepRecord, HRVRecord, BodyBatteryRecord
from fitness.analysis.run_report import RunReport, build_run_report


# ─── In-memory DB fixture ─────────────────────────────────────────────────────

@pytest.fixture(name="engine")
def engine_fixture():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    yield engine
    SQLModel.metadata.drop_all(engine)


@pytest.fixture(name="session")
def session_fixture(engine):
    with Session(engine) as s:
        yield s


# ─── Helpers ──────────────────────────────────────────────────────────────────

def seed_activity(session: Session) -> Activity:
    activity = Activity(
        garmin_activity_id="99887766",
        name="Morning Run",
        activity_type="running",
        start_time_utc=datetime(2025, 1, 15, 7, 30),
        duration_seconds=3600.0,
        distance_meters=8046.72,
        avg_hr=148.0,
        max_hr=172.0,
        total_ascent_meters=85.0,
        total_descent_meters=82.0,
        training_effect_aerobic=3.2,
        vo2max_estimated=47.0,
    )
    session.add(activity)
    session.commit()
    session.refresh(activity)
    return activity


def seed_datapoints(session: Session, activity: Activity, count: int = 720) -> None:
    """Seed a flat steady-state run (approx 5 miles at 7:30/km pace)."""
    speed_ms = 1000.0 / 450.0
    for i in range(count):
        t = i * 5
        session.add(ActivityDatapoint(
            activity_id=activity.id,
            user_id=1,
            elapsed_seconds=t,
            heart_rate=148,
            speed_ms=speed_ms,
            pace_seconds_per_km=450.0,
            elevation_meters=100.0,
            cadence_spm=162,
            distance_meters=float(t) * speed_ms,
            lat=47.606,
            lon=-122.332,
            temperature_c=15.0,
        ))
    session.commit()


def seed_splits(session: Session, activity: Activity) -> None:
    for i in range(6):
        split_type = "run_segment" if i % 2 == 0 else "walk_segment"
        session.add(ActivitySplit(
            activity_id=activity.id,
            user_id=1,
            split_index=i,
            split_type=split_type,
            start_elapsed_seconds=i * 240,
            duration_seconds=240.0,
            distance_meters=500.0,
            avg_hr=150.0 if split_type == "run_segment" else 128.0,
            avg_pace_seconds_per_km=450.0 if split_type == "run_segment" else 800.0,
        ))
    session.commit()


def seed_wellness(session: Session) -> None:
    session.add(SleepRecord(
        sleep_date=date(2025, 1, 14),
        duration_seconds=24600,
        deep_sleep_seconds=4320,
        light_sleep_seconds=11400,
        rem_sleep_seconds=7200,
        awake_seconds=1680,
        sleep_score=74,
        avg_spo2=97.0,
    ))
    session.add(HRVRecord(
        record_date=date(2025, 1, 15),
        weekly_avg_hrv=58.0,
        last_night_avg_hrv=52.0,
        status="BALANCED",
    ))
    session.add(BodyBatteryRecord(
        record_date=date(2025, 1, 15),
        charged_value=78,
        drained_value=32,
    ))
    session.commit()


# ─── Tests ───────────────────────────────────────────────────────────────────

class TestBuildRunReport:
    def test_returns_run_report(self, session, engine):
        activity = seed_activity(session)
        seed_datapoints(session, activity)
        report = build_run_report(activity.id, engine)
        assert isinstance(report, RunReport)

    def test_report_has_activity(self, session, engine):
        activity = seed_activity(session)
        seed_datapoints(session, activity)
        report = build_run_report(activity.id, engine)
        assert report.activity.garmin_activity_id == "99887766"

    def test_report_has_mile_segments(self, session, engine):
        activity = seed_activity(session)
        seed_datapoints(session, activity)
        report = build_run_report(activity.id, engine)
        assert len(report.mile_segments) >= 4

    def test_segment_labels_sequential(self, session, engine):
        activity = seed_activity(session)
        seed_datapoints(session, activity)
        report = build_run_report(activity.id, engine)
        labels = [s.label for s in report.mile_segments]
        for i, label in enumerate(labels):
            assert label == f"Mile {i + 1}"

    def test_bonk_events_is_list(self, session, engine):
        activity = seed_activity(session)
        seed_datapoints(session, activity)
        report = build_run_report(activity.id, engine)
        assert isinstance(report.bonk_events, list)

    def test_no_bonk_on_flat_steady_run(self, session, engine):
        activity = seed_activity(session)
        seed_datapoints(session, activity)
        report = build_run_report(activity.id, engine)
        assert len(report.bonk_events) == 0

    def test_cardiac_drift_is_none_or_event(self, session, engine):
        from fitness.analysis.heart_rate import CardiacDriftEvent
        activity = seed_activity(session)
        seed_datapoints(session, activity)
        report = build_run_report(activity.id, engine)
        assert report.cardiac_drift is None or isinstance(
            report.cardiac_drift, CardiacDriftEvent
        )

    def test_galloway_detection_result_present(self, session, engine):
        from fitness.analysis.galloway import GallowaySegments
        activity = seed_activity(session)
        seed_datapoints(session, activity)
        seed_splits(session, activity)
        report = build_run_report(activity.id, engine)
        assert isinstance(report.galloway, GallowaySegments)

    def test_galloway_detects_run_walk(self, session, engine):
        activity = seed_activity(session)
        seed_datapoints(session, activity)
        seed_splits(session, activity)
        report = build_run_report(activity.id, engine)
        assert report.galloway.is_galloway is True

    def test_wellness_sleep_attached(self, session, engine):
        activity = seed_activity(session)
        seed_datapoints(session, activity)
        seed_wellness(session)
        report = build_run_report(activity.id, engine)
        assert report.sleep is not None
        assert report.sleep.sleep_score == 74

    def test_wellness_hrv_attached(self, session, engine):
        activity = seed_activity(session)
        seed_datapoints(session, activity)
        seed_wellness(session)
        report = build_run_report(activity.id, engine)
        assert report.hrv is not None
        assert report.hrv.last_night_avg_hrv == pytest.approx(52.0)

    def test_wellness_body_battery_attached(self, session, engine):
        activity = seed_activity(session)
        seed_datapoints(session, activity)
        seed_wellness(session)
        report = build_run_report(activity.id, engine)
        assert report.body_battery is not None
        assert report.body_battery.charged_value == 78

    def test_missing_wellness_returns_none(self, session, engine):
        activity = seed_activity(session)
        seed_datapoints(session, activity)
        # No wellness seeded
        report = build_run_report(activity.id, engine)
        assert report.sleep is None
        assert report.hrv is None
        assert report.body_battery is None

    def test_invalid_activity_id_raises(self, session, engine):
        with pytest.raises(ValueError):
            build_run_report(99999, engine)

    def test_workout_classification_none_when_no_workout_json(self, session, engine):
        """When activity has no workout_definition_json, classification is None."""
        activity = seed_activity(session)  # no workout_definition_json set
        seed_datapoints(session, activity)
        report = build_run_report(activity.id, engine)
        assert report.workout_classification is None

    def test_workout_classification_present_when_workout_json_set(self, session, engine):
        """When activity has workout_definition_json, classification is a WorkoutClassification."""
        import json
        from fitness.analysis.workout_classifier import WorkoutClassification
        activity = seed_activity(session)
        activity.workout_definition_json = json.dumps({
            "workoutId": 12345,
            "workoutName": "Speed Repeats",
            "description": "Fast intervals.",
            "workoutSegments": [],
        })
        session.add(activity)
        session.commit()
        seed_datapoints(session, activity)
        report = build_run_report(activity.id, engine)
        assert report.workout_classification is not None
        assert isinstance(report.workout_classification, WorkoutClassification)
        assert report.workout_classification.workout_name == "Speed Repeats"
