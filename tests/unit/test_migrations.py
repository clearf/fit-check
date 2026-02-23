"""Tests for database migration helpers."""
from datetime import datetime

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from fitness.db.migrations import run_migrations
from fitness.models.activity import Activity, ActivitySplit


@pytest.fixture(name="migration_engine")
def migration_engine_fixture():
    """In-memory SQLite engine with full schema, for testing migrations."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    yield engine
    SQLModel.metadata.drop_all(engine)


class TestRunMigrations:
    def test_run_migrations_does_not_raise(self, migration_engine):
        """Migration should complete without errors on a fresh DB."""
        run_migrations(migration_engine)

    def test_run_migrations_is_idempotent(self, migration_engine):
        """Running migrations twice must not raise (columns already exist)."""
        run_migrations(migration_engine)
        run_migrations(migration_engine)  # second call must be safe

    def test_wkt_step_index_column_exists_after_migration(self, migration_engine):
        """activitysplit.wkt_step_index is queryable after migration."""
        run_migrations(migration_engine)
        with Session(migration_engine) as s:
            # Insert an activity first (FK requirement)
            act = Activity(
                garmin_activity_id="mig-test-1",
                name="Test",
                activity_type="running",
                start_time_utc=datetime(2026, 1, 1, 8, 0),
                duration_seconds=1800.0,
                distance_meters=5000.0,
            )
            s.add(act)
            s.commit()
            s.refresh(act)

            sp = ActivitySplit(
                activity_id=act.id,
                split_index=0,
                split_type="run_segment",
                start_elapsed_seconds=0,
                duration_seconds=227.0,
                distance_meters=800.0,
                wkt_step_index=9,
            )
            s.add(sp)
            s.commit()
            s.refresh(sp)

            result = s.exec(select(ActivitySplit)).first()
            assert result.wkt_step_index == 9

    def test_target_pace_columns_exist_after_migration(self, migration_engine):
        """target_pace_slow/fast columns are queryable after migration."""
        run_migrations(migration_engine)
        with Session(migration_engine) as s:
            act = Activity(
                garmin_activity_id="mig-test-2",
                name="Test",
                activity_type="running",
                start_time_utc=datetime(2026, 1, 1, 8, 0),
                duration_seconds=1800.0,
                distance_meters=5000.0,
            )
            s.add(act)
            s.commit()
            s.refresh(act)

            sp = ActivitySplit(
                activity_id=act.id,
                split_index=0,
                split_type="run_segment",
                start_elapsed_seconds=0,
                duration_seconds=227.0,
                distance_meters=800.0,
                target_pace_slow_s_per_km=282.6,
                target_pace_fast_s_per_km=295.1,
            )
            s.add(sp)
            s.commit()
            s.refresh(sp)

            result = s.exec(select(ActivitySplit)).first()
            assert result.target_pace_slow_s_per_km == pytest.approx(282.6)
            assert result.target_pace_fast_s_per_km == pytest.approx(295.1)

    def test_workout_definition_json_column_exists_after_migration(self, migration_engine):
        """activity.workout_definition_json is queryable after migration."""
        run_migrations(migration_engine)
        with Session(migration_engine) as s:
            act = Activity(
                garmin_activity_id="mig-test-3",
                name="Test",
                activity_type="running",
                start_time_utc=datetime(2026, 1, 1, 8, 0),
                duration_seconds=1800.0,
                distance_meters=5000.0,
                workout_definition_json='{"workoutId": 123}',
            )
            s.add(act)
            s.commit()
            s.refresh(act)

            result = s.exec(select(Activity)).first()
            assert result.workout_definition_json == '{"workoutId": 123}'

    def test_new_columns_default_to_none(self, migration_engine):
        """New columns are nullable and default to None."""
        run_migrations(migration_engine)
        with Session(migration_engine) as s:
            act = Activity(
                garmin_activity_id="mig-test-4",
                name="Test",
                activity_type="running",
                start_time_utc=datetime(2026, 1, 1, 8, 0),
                duration_seconds=1800.0,
                distance_meters=5000.0,
            )
            s.add(act)
            s.commit()
            s.refresh(act)

            sp = ActivitySplit(
                activity_id=act.id,
                split_index=0,
                split_type="run_segment",
                start_elapsed_seconds=0,
                duration_seconds=227.0,
                distance_meters=800.0,
            )
            s.add(sp)
            s.commit()
            s.refresh(sp)

            assert sp.wkt_step_index is None
            assert sp.target_pace_slow_s_per_km is None
            assert sp.target_pace_fast_s_per_km is None
            assert act.workout_definition_json is None
