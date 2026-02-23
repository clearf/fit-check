"""SQLModel engine singleton and session dependency."""
from contextlib import contextmanager
from typing import Generator, Optional

from sqlmodel import Session, SQLModel, create_engine

from fitness.config import get_settings

_engine = None


def get_engine():
    """Return the module-level engine, creating it on first call."""
    global _engine
    if _engine is None:
        settings = get_settings()
        _engine = create_engine(
            settings.database_url,
            connect_args={"check_same_thread": False},  # SQLite only; safe for FastAPI
        )
        # Import all models so metadata is populated before create_all
        from fitness.models.activity import Activity, ActivityDatapoint, ActivitySplit  # noqa
        from fitness.models.wellness import SleepRecord, HRVRecord, BodyBatteryRecord  # noqa
        from fitness.models.sync import SyncLog  # noqa
        SQLModel.metadata.create_all(_engine)
        from fitness.db.migrations import run_migrations
        run_migrations(_engine)
    return _engine


def get_session() -> Generator[Session, None, None]:
    """FastAPI dependency that yields a DB session."""
    with Session(get_engine()) as session:
        yield session
