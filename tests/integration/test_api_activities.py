"""Integration tests for /activities routes."""
from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from fitness.models.activity import Activity
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


@pytest.fixture(name="seeded_activities")
def seeded_activities_fixture(engine):
    with Session(engine) as s:
        for i in range(3):
            s.add(Activity(
                garmin_activity_id=f"act_{i}",
                name=f"Run {i}",
                activity_type="running",
                start_time_utc=datetime(2025, 1, 15 - i, 7, 30),
                duration_seconds=3600.0,
                distance_meters=8000.0,
                avg_hr=148.0,
            ))
        s.commit()


class TestActivityRoutes:
    def test_list_activities_empty(self, client):
        resp = client.get("/activities/")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_list_activities_returns_all(self, client, seeded_activities):
        resp = client.get("/activities/")
        assert resp.status_code == 200
        assert len(resp.json()) == 3

    def test_list_activities_newest_first(self, client, seeded_activities):
        resp = client.get("/activities/")
        dates = [a["start_time_utc"] for a in resp.json()]
        assert dates == sorted(dates, reverse=True)

    def test_list_activities_limit(self, client, seeded_activities):
        resp = client.get("/activities/?limit=2")
        assert resp.status_code == 200
        assert len(resp.json()) == 2

    def test_get_activity_by_id(self, client, engine, seeded_activities):
        with Session(engine) as s:
            act = s.exec(
                __import__("sqlmodel").select(Activity)
            ).first()
        resp = client.get(f"/activities/{act.id}")
        assert resp.status_code == 200
        assert resp.json()["garmin_activity_id"] == act.garmin_activity_id

    def test_get_activity_not_found(self, client):
        resp = client.get("/activities/99999")
        assert resp.status_code == 404

    def test_get_by_garmin_id(self, client, seeded_activities):
        resp = client.get("/activities/garmin/act_0")
        assert resp.status_code == 200
        assert resp.json()["garmin_activity_id"] == "act_0"

    def test_get_by_garmin_id_not_found(self, client):
        resp = client.get("/activities/garmin/NONEXISTENT")
        assert resp.status_code == 404
