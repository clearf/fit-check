"""
Database migrations for fitness bot.

Uses SQLite ALTER TABLE ADD COLUMN for incremental schema evolution.
Each migration is idempotent: columns are only added if absent.

Called automatically from get_engine() after create_all() so both
fresh installs and existing DBs are handled without manual steps.
"""
from sqlalchemy import text


def run_migrations(engine) -> None:
    """Apply all pending schema migrations.

    Safe to call multiple times — checks column existence before altering.
    Supports SQLite only (uses PRAGMA table_info).

    Args:
        engine: SQLAlchemy engine (SQLModel create_engine result).
    """
    with engine.connect() as conn:
        # ActivitySplit: workout step linkage and target pace band
        _add_column_if_missing(conn, "activitysplit", "wkt_step_index", "INTEGER")
        _add_column_if_missing(conn, "activitysplit", "target_pace_slow_s_per_km", "REAL")
        _add_column_if_missing(conn, "activitysplit", "target_pace_fast_s_per_km", "REAL")

        # Activity: cached workout definition JSON from Garmin workout service
        _add_column_if_missing(conn, "activity", "workout_definition_json", "TEXT")

        conn.commit()


def _add_column_if_missing(conn, table: str, column: str, col_type: str) -> None:
    """Add a column to a table if it doesn't already exist.

    Args:
        conn: SQLAlchemy connection.
        table: Table name (lowercase, as SQLite stores it).
        column: Column name to add.
        col_type: SQLite type string, e.g. "INTEGER", "REAL", "TEXT".
    """
    result = conn.execute(text(f"PRAGMA table_info({table})"))
    existing_columns = {row[1] for row in result}
    if column not in existing_columns:
        conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}"))
