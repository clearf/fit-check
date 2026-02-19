"""Integration tests for /sync routes."""
from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from fitness.models.activity import Activity
from fitness.models.sync import SyncLog
from fitness.api.main import create_app
from fitness.db.engine import get_session


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


@pytest.fixture(name="client")
def client_fixture(engine):
    app = create_app()

    def override_session():
        with Session(engine) as s:
            yield s

    app.dependency_overrides[get_session] = override_session
    with TestClient(app) as c:
        yield c


class TestSyncRoutes:
    def test_trigger_returns_200(self, client):
        # Patch _do_sync so the background task doesn't hit real Garmin
        with patch("fitness.api.routes.sync._do_sync", new=AsyncMock()):
            resp = client.post("/sync/trigger", json={})
        assert resp.status_code == 200
        assert "started" in resp.json()["message"].lower()

    def test_trigger_with_activity_id(self, client):
        with patch("fitness.api.routes.sync._do_sync", new=AsyncMock()):
            resp = client.post("/sync/trigger", json={"activity_id": "12345"})
        assert resp.status_code == 200
        assert resp.json()["activity_id"] == "12345"

    def test_status_never_run(self, client):
        resp = client.get("/sync/status")
        assert resp.status_code == 200
        assert resp.json()["status"] == "never_run"

    def test_status_after_log_created(self, client, engine):
        with Session(engine) as s:
            s.add(SyncLog(
                started_at=datetime(2025, 1, 15, 7, 0),
                finished_at=datetime(2025, 1, 15, 7, 1),
                status="success",
                activities_synced=1,
            ))
            s.commit()
        resp = client.get("/sync/status")
        assert resp.status_code == 200
        assert resp.json()["status"] == "success"
        assert resp.json()["activities_synced"] == 1

    def test_latest_no_activities(self, client):
        resp = client.get("/sync/latest")
        assert resp.status_code == 200
        assert resp.json() is None

    def test_latest_returns_most_recent(self, client, engine):
        with Session(engine) as s:
            for i in range(3):
                s.add(Activity(
                    garmin_activity_id=f"act_{i}",
                    name=f"Run {i}",
                    activity_type="running",
                    start_time_utc=datetime(2025, 1, 10 + i, 7, 30),
                    duration_seconds=3600.0,
                    distance_meters=8000.0,
                ))
            s.commit()
        resp = client.get("/sync/latest")
        assert resp.status_code == 200
        assert resp.json()["garmin_activity_id"] == "act_2"
