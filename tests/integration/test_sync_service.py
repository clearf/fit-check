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
        assert activity.garmin_activity_id == "17345678901"

    @pytest.mark.asyncio
    async def test_sync_activity_name(self, service, engine):
        await service.sync_activity("17345678901")
        with Session(engine) as s:
            activity = s.exec(select(Activity)).first()
        assert activity.name == "Morning Run"

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
        assert activity.avg_hr == pytest.approx(148.0)

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
