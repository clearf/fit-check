"""
Integration tests for GarminSyncService.

Uses AsyncMock for the Garmin client and an in-memory SQLite DB.
No real network calls are made.
"""
import json
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from fitness.models.activity import Activity, ActivityDatapoint, ActivitySplit
from fitness.models.wellness import HRVRecord, SleepRecord
from fitness.models.sync import SyncLog
from fitness.garmin.sync_service import GarminSyncService

FIXTURES = Path(__file__).parent.parent / "fixtures"


# ─── Shared in-memory DB ──────────────────────────────────────────────────────

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


@pytest.fixture(name="test_session")
def test_session_fixture(engine):
    with Session(engine) as session:
        yield session


# ─── Mock Garmin client ───────────────────────────────────────────────────────

ACTIVITY_SUMMARY = json.loads((FIXTURES / "garmin_activity_summary.json").read_text())
TYPED_SPLITS = json.loads((FIXTURES / "garmin_typed_splits.json").read_text())
SLEEP_DATA = json.loads((FIXTURES / "garmin_sleep.json").read_text())
HRV_DATA = json.loads((FIXTURES / "garmin_hrv.json").read_text())
WORKOUT_DEF = json.loads((FIXTURES / "garmin_workout.json").read_text())

# Minimal FIT datapoints (as if parsed from a .fit file)
FAKE_DATAPOINTS = [
    {
        "elapsed_seconds": i * 5,
        "heart_rate": 148,
        "speed_ms": 2.222,
        "pace_seconds_per_km": 450.0,
        "elevation_meters": 100.0 + i * 0.1,
        "cadence_spm": 162,
        "distance_meters": float(i * 5) * 2.222,
        "lat": 47.606 + i * 0.0001,
        "lon": -122.332,
        "temperature_c": 15.0,
    }
    for i in range(200)
]


def make_mock_client(
    activity_summary=None,
    typed_splits=None,
    sleep_data=None,
    hrv_data=None,
    datapoints=None,
    workout_def=None,
):
    client = AsyncMock()
    client.get_activity_summary = AsyncMock(
        return_value=activity_summary or ACTIVITY_SUMMARY
    )
    client.get_activity_typed_splits = AsyncMock(
        return_value=typed_splits or TYPED_SPLITS
    )
    client.get_sleep_data = AsyncMock(return_value=sleep_data or SLEEP_DATA)
    client.get_hrv_data = AsyncMock(return_value=hrv_data or HRV_DATA)
    client.get_fit_datapoints = AsyncMock(
        return_value=datapoints or FAKE_DATAPOINTS
    )
    client.get_workout = AsyncMock(
        return_value=workout_def or WORKOUT_DEF
    )
    return client


# ─── Tests ───────────────────────────────────────────────────────────────────

class TestGarminSyncService:
    @pytest.fixture
    def service(self, engine):
        client = make_mock_client()
        return GarminSyncService(client=client, engine=engine)

    @pytest.mark.asyncio
    async def test_sync_creates_activity(self, service, engine):
        await service.sync_activity("17345678901")
        with Session(engine) as s:
            activity = s.exec(select(Activity)).first()
        assert activity is not None
        # garmin_activity_id comes from the fixture response (activityId field),
        # not the argument passed to sync_activity.
        assert activity.garmin_activity_id == "10000000001"

    @pytest.mark.asyncio
    async def test_sync_activity_name(self, service, engine):
        await service.sync_activity("17345678901")
        with Session(engine) as s:
            activity = s.exec(select(Activity)).first()
        assert activity.name == "Seattle - Speed Repeats"

    @pytest.mark.asyncio
    async def test_sync_creates_datapoints(self, service, engine):
        await service.sync_activity("17345678901")
        with Session(engine) as s:
            count = len(s.exec(select(ActivityDatapoint)).all())
        assert count == len(FAKE_DATAPOINTS)

    @pytest.mark.asyncio
    async def test_sync_creates_splits(self, service, engine):
        await service.sync_activity("17345678901")
        with Session(engine) as s:
            splits = s.exec(select(ActivitySplit)).all()
        assert len(splits) == len(TYPED_SPLITS)

    @pytest.mark.asyncio
    async def test_sync_idempotent_no_duplicate_activity(self, service, engine):
        """Syncing the same activity twice must not create duplicates."""
        await service.sync_activity("17345678901")
        await service.sync_activity("17345678901")
        with Session(engine) as s:
            activities = s.exec(select(Activity)).all()
        assert len(activities) == 1

    @pytest.mark.asyncio
    async def test_sync_idempotent_no_duplicate_datapoints(self, service, engine):
        """Re-syncing must not duplicate datapoints."""
        await service.sync_activity("17345678901")
        await service.sync_activity("17345678901")
        with Session(engine) as s:
            count = len(s.exec(select(ActivityDatapoint)).all())
        assert count == len(FAKE_DATAPOINTS)

    @pytest.mark.asyncio
    async def test_sync_creates_sync_log(self, service, engine):
        await service.sync_activity("17345678901")
        with Session(engine) as s:
            log = s.exec(select(SyncLog)).first()
        assert log is not None
        assert log.status == "success"

    @pytest.mark.asyncio
    async def test_sync_log_records_activity_count(self, service, engine):
        await service.sync_activity("17345678901")
        with Session(engine) as s:
            log = s.exec(select(SyncLog)).first()
        assert log.activities_synced == 1

    @pytest.mark.asyncio
    async def test_sync_split_types_correct(self, service, engine):
        await service.sync_activity("17345678901")
        with Session(engine) as s:
            splits = s.exec(select(ActivitySplit)).all()
        types = {sp.split_type for sp in splits}
        assert "run_segment" in types
        assert "walk_segment" in types

    @pytest.mark.asyncio
    async def test_sync_activity_hr_populated(self, service, engine):
        await service.sync_activity("17345678901")
        with Session(engine) as s:
            activity = s.exec(select(Activity)).first()
        # avg_hr comes from summaryDTO.averageHR in the real fixture
        assert activity.avg_hr == pytest.approx(133.0)

    @pytest.mark.asyncio
    async def test_sync_error_logs_failure(self, engine):
        """If the client raises, the sync log records error status."""
        client = make_mock_client()
        client.get_activity_summary = AsyncMock(
            side_effect=Exception("Garmin API down")
        )
        service = GarminSyncService(client=client, engine=engine)
        with pytest.raises(Exception):
            await service.sync_activity("17345678901")
        with Session(engine) as s:
            log = s.exec(select(SyncLog)).first()
        assert log.status == "error"
        assert "Garmin API down" in log.error_message


# ─── Workout sync tests ───────────────────────────────────────────────────────

class TestWorkoutSync:
    """Tests for workout definition fetch and split target enrichment."""

    @pytest.fixture
    def service(self, engine):
        client = make_mock_client()
        return GarminSyncService(client=client, engine=engine)

    @pytest.mark.asyncio
    async def test_workout_definition_stored_on_activity(self, service, engine):
        """workout_definition_json is populated from the workout service response."""
        await service.sync_activity("17345678901")
        with Session(engine) as s:
            act = s.exec(select(Activity)).first()
        assert act.workout_definition_json is not None
        wdef = json.loads(act.workout_definition_json)
        assert wdef["workoutId"] == 1467965958

    @pytest.mark.asyncio
    async def test_splits_have_wkt_step_index(self, service, engine):
        """ActivitySplit rows are annotated with wkt_step_index from lapDTO."""
        await service.sync_activity("17345678901")
        with Session(engine) as s:
            splits = s.exec(select(ActivitySplit).order_by(ActivitySplit.split_index)).all()
        # ACTIVE splits in fixture have wktStepIndex=9
        active_splits = [sp for sp in splits if sp.split_type == "run_segment"]
        assert len(active_splits) > 0
        assert all(sp.wkt_step_index == 9 for sp in active_splits)

    @pytest.mark.asyncio
    async def test_speed_interval_splits_have_target_pace(self, service, engine):
        """ACTIVE splits (wktStepIndex=9 = 800m interval) get target pace bands."""
        await service.sync_activity("17345678901")
        with Session(engine) as s:
            splits = s.exec(
                select(ActivitySplit).where(ActivitySplit.wkt_step_index == 9)
            ).all()
        assert len(splits) > 0
        for sp in splits:
            assert sp.target_pace_slow_s_per_km is not None
            assert sp.target_pace_fast_s_per_km is not None
            # Sanity check: slow pace > fast pace (more s/km = slower)
            assert sp.target_pace_slow_s_per_km > sp.target_pace_fast_s_per_km

    @pytest.mark.asyncio
    async def test_recovery_splits_have_no_target_pace(self, service, engine):
        """RECOVERY splits (wktStepIndex=11 = 3min walk, no.target) have None pace targets."""
        await service.sync_activity("17345678901")
        with Session(engine) as s:
            splits = s.exec(
                select(ActivitySplit).where(ActivitySplit.wkt_step_index == 11)
            ).all()
        assert len(splits) > 0
        for sp in splits:
            assert sp.target_pace_slow_s_per_km is None
            assert sp.target_pace_fast_s_per_km is None

    @pytest.mark.asyncio
    async def test_no_workout_id_skips_get_workout(self, engine):
        """If the activity summary has no associatedWorkoutId, get_workout is not called."""
        summary_no_workout = json.loads(
            (FIXTURES / "garmin_activity_summary.json").read_text()
        )
        summary_no_workout["metadataDTO"]["associatedWorkoutId"] = None

        client = make_mock_client(activity_summary=summary_no_workout)
        service = GarminSyncService(client=client, engine=engine)
        await service.sync_activity("17345678901")

        client.get_workout.assert_not_called()
        with Session(engine) as s:
            act = s.exec(select(Activity)).first()
        assert act is not None
        assert act.workout_definition_json is None

    @pytest.mark.asyncio
    async def test_get_workout_failure_is_nonfatal(self, engine):
        """If get_workout() raises (network error), the sync succeeds with no workout data."""
        client = make_mock_client()
        client.get_workout = AsyncMock(side_effect=Exception("network error"))
        service = GarminSyncService(client=client, engine=engine)

        # Should not raise — workout fetch is non-fatal
        await service.sync_activity("17345678901")

        with Session(engine) as s:
            act = s.exec(select(Activity)).first()
        assert act is not None
        assert act.workout_definition_json is None

    @pytest.mark.asyncio
    async def test_splits_have_no_targets_when_workout_fetch_fails(self, engine):
        """When get_workout() fails, splits still exist but without target pace data."""
        client = make_mock_client()
        client.get_workout = AsyncMock(side_effect=Exception("network error"))
        service = GarminSyncService(client=client, engine=engine)
        await service.sync_activity("17345678901")

        with Session(engine) as s:
            splits = s.exec(select(ActivitySplit)).all()
        assert len(splits) > 0
        # No target pace without workout data
        for sp in splits:
            assert sp.target_pace_slow_s_per_km is None
            assert sp.target_pace_fast_s_per_km is None
