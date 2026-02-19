"""Wellness context models: sleep, HRV, body battery."""
from datetime import date, datetime
from typing import Optional

from sqlmodel import Field, SQLModel


class SleepRecord(SQLModel, table=True):
    """Nightly sleep data from Garmin Connect."""

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(default=1, index=True)
    sleep_date: date = Field(index=True)  # the night of (date you went to sleep)

    duration_seconds: Optional[int] = None
    deep_sleep_seconds: Optional[int] = None
    light_sleep_seconds: Optional[int] = None
    rem_sleep_seconds: Optional[int] = None
    awake_seconds: Optional[int] = None
    sleep_score: Optional[int] = None  # Garmin sleep score 0-100
    avg_spo2: Optional[float] = None
    avg_respiration: Optional[float] = None

    raw_json: Optional[str] = None
    synced_at: datetime = Field(default_factory=datetime.utcnow)


class HRVRecord(SQLModel, table=True):
    """Daily HRV snapshot from Garmin."""

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(default=1, index=True)
    record_date: date = Field(index=True)

    weekly_avg_hrv: Optional[float] = None
    last_night_avg_hrv: Optional[float] = None
    last_night_5min_high: Optional[float] = None
    status: Optional[str] = None  # "BALANCED", "UNBALANCED", "LOW", etc.

    raw_json: Optional[str] = None
    synced_at: datetime = Field(default_factory=datetime.utcnow)


class BodyBatteryRecord(SQLModel, table=True):
    """Daily body battery charge/drain from Garmin."""

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(default=1, index=True)
    record_date: date = Field(index=True)

    charged_value: Optional[int] = None  # peak battery after sleep (0-100)
    drained_value: Optional[int] = None  # minimum during the day (0-100)

    raw_json: Optional[str] = None
    synced_at: datetime = Field(default_factory=datetime.utcnow)
