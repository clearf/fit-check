"""Shared test fixtures."""
from datetime import datetime
from pathlib import Path
from typing import Generator

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

# Import all models so SQLModel.metadata knows about them
from fitness.models.activity import Activity, ActivityDatapoint, ActivitySplit  # noqa: F401
from fitness.models.wellness import BodyBatteryRecord, HRVRecord, SleepRecord  # noqa: F401
from fitness.models.sync import SyncLog  # noqa: F401

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture(name="engine")
def engine_fixture():
    """In-memory SQLite engine. Tables recreated fresh for each test session."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    yield engine
    SQLModel.metadata.drop_all(engine)


@pytest.fixture(name="test_session")
def test_session_fixture(engine) -> Generator[Session, None, None]:
    """Provides a DB session connected to in-memory SQLite."""
    with Session(engine) as session:
        yield session


@pytest.fixture(name="seeded_activity")
def seeded_activity_fixture(test_session: Session) -> Activity:
    """A persisted Activity for use in datapoint/split tests."""
    activity = Activity(
        garmin_activity_id="1234567890",
        name="Morning Run",
        activity_type="running",
        start_time_utc=datetime(2025, 1, 15, 7, 30),
        duration_seconds=3600.0,
        distance_meters=8046.72,
        avg_hr=148.0,
        max_hr=172.0,
        total_ascent_meters=85.0,
        total_descent_meters=82.0,
    )
    test_session.add(activity)
    test_session.commit()
    test_session.refresh(activity)
    return activity
