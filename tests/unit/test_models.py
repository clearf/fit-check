"""Tests for DB models — written first (TDD)."""
from datetime import date, datetime

import pytest
from sqlmodel import Session, select

from fitness.models.activity import Activity, ActivityDatapoint, ActivitySplit
from fitness.models.sync import SyncLog
from fitness.models.wellness import BodyBatteryRecord, HRVRecord, SleepRecord


class TestActivity:
    def test_default_user_id_is_one(self):
        activity = Activity(
            garmin_activity_id="12345",
            name="Morning Run",
            activity_type="running",
            start_time_utc=datetime(2025, 1, 15, 7, 30),
            duration_seconds=3600.0,
            distance_meters=8046.72,
        )
        assert activity.user_id == 1

    def test_optional_fields_default_to_none(self):
        activity = Activity(
            garmin_activity_id="12345",
            name="Morning Run",
            activity_type="running",
            start_time_utc=datetime(2025, 1, 15, 7, 30),
            duration_seconds=3600.0,
            distance_meters=8046.72,
        )
        assert activity.avg_hr is None
        assert activity.max_hr is None
        assert activity.vo2max_estimated is None
        assert activity.fit_file_path is None

    def test_persists_and_retrieves_from_db(self, test_session: Session):
        activity = Activity(
            garmin_activity_id="abc123",
            name="Evening Run",
            activity_type="running",
            start_time_utc=datetime(2025, 2, 1, 18, 0),
            duration_seconds=1800.0,
            distance_meters=5000.0,
            avg_hr=152.0,
            max_hr=178.0,
            total_ascent_meters=45.0,
        )
        test_session.add(activity)
        test_session.commit()
        test_session.refresh(activity)

        result = test_session.exec(
            select(Activity).where(Activity.garmin_activity_id == "abc123")
        ).first()
        assert result is not None
        assert result.name == "Evening Run"
        assert result.avg_hr == 152.0

    def test_garmin_activity_id_is_unique(self, test_session: Session):
        """Idempotency guard: duplicate garmin_activity_id should fail at DB level."""
        import sqlalchemy.exc

        a1 = Activity(
            garmin_activity_id="dup123",
            name="Run 1",
            activity_type="running",
            start_time_utc=datetime(2025, 1, 1, 7, 0),
            duration_seconds=1800.0,
            distance_meters=5000.0,
        )
        a2 = Activity(
            garmin_activity_id="dup123",
            name="Run 2",
            activity_type="running",
            start_time_utc=datetime(2025, 1, 2, 7, 0),
            duration_seconds=1800.0,
            distance_meters=5000.0,
        )
        test_session.add(a1)
        test_session.commit()
        test_session.add(a2)
        with pytest.raises(sqlalchemy.exc.IntegrityError):
            test_session.commit()


class TestActivityDatapoint:
    def test_defaults(self):
        dp = ActivityDatapoint(activity_id=1, elapsed_seconds=60)
        assert dp.user_id == 1
        assert dp.heart_rate is None
        assert dp.pace_seconds_per_km is None
        assert dp.elevation_meters is None

    def test_persists_with_all_fields(self, test_session: Session, seeded_activity: Activity):
        dp = ActivityDatapoint(
            activity_id=seeded_activity.id,
            user_id=1,
            elapsed_seconds=120,
            heart_rate=148,
            speed_ms=2.778,
            pace_seconds_per_km=360.0,
            elevation_meters=105.3,
            cadence_spm=162,
            distance_meters=333.3,
            lat=47.6062,
            lon=-122.3321,
            temperature_c=12.5,
        )
        test_session.add(dp)
        test_session.commit()
        test_session.refresh(dp)

        result = test_session.exec(
            select(ActivityDatapoint).where(ActivityDatapoint.activity_id == seeded_activity.id)
        ).first()
        assert result.heart_rate == 148
        assert result.pace_seconds_per_km == 360.0
        assert result.temperature_c == 12.5


class TestActivitySplit:
    def test_split_types(self, test_session: Session, seeded_activity: Activity):
        run_split = ActivitySplit(
            activity_id=seeded_activity.id,
            split_index=0,
            split_type="run_segment",
            start_elapsed_seconds=0,
            duration_seconds=180.0,
            distance_meters=600.0,
            avg_hr=145.0,
            avg_pace_seconds_per_km=300.0,
        )
        walk_split = ActivitySplit(
            activity_id=seeded_activity.id,
            split_index=1,
            split_type="walk_segment",
            start_elapsed_seconds=180,
            duration_seconds=60.0,
            distance_meters=80.0,
            avg_hr=128.0,
            avg_pace_seconds_per_km=750.0,
        )
        test_session.add(run_split)
        test_session.add(walk_split)
        test_session.commit()

        splits = test_session.exec(
            select(ActivitySplit).where(ActivitySplit.activity_id == seeded_activity.id)
        ).all()
        assert len(splits) == 2
        types = {s.split_type for s in splits}
        assert "run_segment" in types
        assert "walk_segment" in types


class TestWellnessModels:
    def test_sleep_record(self, test_session: Session):
        sleep = SleepRecord(
            sleep_date=date(2025, 1, 14),
            duration_seconds=24120,  # 6h 42m
            deep_sleep_seconds=4080,  # 1h 8m
            rem_sleep_seconds=5400,
            sleep_score=71,
        )
        test_session.add(sleep)
        test_session.commit()

        result = test_session.exec(
            select(SleepRecord).where(SleepRecord.sleep_date == date(2025, 1, 14))
        ).first()
        assert result.sleep_score == 71
        assert result.duration_seconds == 24120

    def test_hrv_record(self, test_session: Session):
        hrv = HRVRecord(
            record_date=date(2025, 1, 15),
            weekly_avg_hrv=58.0,
            last_night_avg_hrv=52.0,
            status="UNBALANCED",
        )
        test_session.add(hrv)
        test_session.commit()

        result = test_session.exec(
            select(HRVRecord).where(HRVRecord.record_date == date(2025, 1, 15))
        ).first()
        assert result.weekly_avg_hrv == 58.0
        assert result.status == "UNBALANCED"

    def test_body_battery_record(self, test_session: Session):
        bb = BodyBatteryRecord(
            record_date=date(2025, 1, 15),
            charged_value=82,
            drained_value=34,
        )
        test_session.add(bb)
        test_session.commit()

        result = test_session.exec(
            select(BodyBatteryRecord).where(BodyBatteryRecord.record_date == date(2025, 1, 15))
        ).first()
        assert result.charged_value == 82
        assert result.drained_value == 34


class TestSyncLog:
    def test_default_status_is_running(self, test_session: Session):
        log = SyncLog(user_id=1, activities_synced=0)
        test_session.add(log)
        test_session.commit()
        test_session.refresh(log)

        assert log.status == "running"
        assert log.finished_at is None

    def test_update_to_success(self, test_session: Session):
        log = SyncLog(user_id=1)
        test_session.add(log)
        test_session.commit()

        log.status = "success"
        log.activities_synced = 3
        log.finished_at = datetime.utcnow()
        test_session.add(log)
        test_session.commit()
        test_session.refresh(log)

        assert log.status == "success"
        assert log.activities_synced == 3
        assert log.finished_at is not None
