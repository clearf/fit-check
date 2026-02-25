"""Activity data models: runs, per-second datapoints, and splits."""
from datetime import datetime
from typing import List, Optional

from sqlmodel import Field, Relationship, SQLModel


class Activity(SQLModel, table=True):
    """One row per Garmin activity (runs only for MVP)."""

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(default=1, index=True)
    garmin_activity_id: str = Field(unique=True, index=True)
    name: str
    activity_type: str  # "running", "trail_running", etc.
    start_time_utc: datetime
    duration_seconds: float
    distance_meters: float

    # Heart rate summary
    avg_hr: Optional[float] = None
    max_hr: Optional[float] = None

    # Pace / elevation
    avg_pace_seconds_per_km: Optional[float] = None
    total_ascent_meters: Optional[float] = None
    total_descent_meters: Optional[float] = None
    avg_cadence: Optional[float] = None

    # Garmin computed metrics (from API summary, not FIT file)
    training_effect_aerobic: Optional[float] = None
    training_effect_anaerobic: Optional[float] = None
    vo2max_estimated: Optional[float] = None
    weather_temp_c: Optional[float] = None

    # Raw JSON blob for full API response reference
    raw_summary_json: Optional[str] = None

    # Structured workout definition from Garmin workout service (if activity had a linked workout)
    workout_definition_json: Optional[str] = None

    # Path to the downloaded .fit file on disk
    fit_file_path: Optional[str] = None

    synced_at: datetime = Field(default_factory=datetime.utcnow)

    # Relationships
    datapoints: List["ActivityDatapoint"] = Relationship(back_populates="activity")
    splits: List["ActivitySplit"] = Relationship(back_populates="activity")


class ActivityDatapoint(SQLModel, table=True):
    """
    One row per FIT record message (~1 per second for a Forerunner 245).
    A 60-minute run produces ~3600 rows.
    """

    id: Optional[int] = Field(default=None, primary_key=True)
    activity_id: int = Field(foreign_key="activity.id", index=True)
    user_id: int = Field(default=1)

    elapsed_seconds: int  # seconds since activity start

    # Per-point metrics — nullable (device may not record every field at every sample)
    heart_rate: Optional[int] = None  # bpm
    speed_ms: Optional[float] = None  # m/s (raw from FIT enhanced_speed)
    pace_seconds_per_km: Optional[float] = None  # derived: 1000 / speed_ms
    elevation_meters: Optional[float] = None  # from FIT enhanced_altitude
    cadence_spm: Optional[int] = None  # steps per minute
    distance_meters: Optional[float] = None  # cumulative distance from activity start
    lat: Optional[float] = None  # degrees (converted from Garmin semicircles)
    lon: Optional[float] = None
    temperature_c: Optional[float] = None

    # Relationship
    activity: Optional[Activity] = Relationship(back_populates="datapoints")


class ActivitySplit(SQLModel, table=True):
    """
    One row per lap or typed segment (run/walk).
    Sources: Garmin lap button presses + typed splits API for Galloway labeling.
    """

    id: Optional[int] = Field(default=None, primary_key=True)
    activity_id: int = Field(foreign_key="activity.id", index=True)
    user_id: int = Field(default=1)

    split_index: int
    split_type: str  # "lap", "run_segment", "walk_segment"
    start_elapsed_seconds: int
    duration_seconds: float
    distance_meters: float

    avg_hr: Optional[float] = None
    avg_pace_seconds_per_km: Optional[float] = None
    total_ascent_meters: Optional[float] = None

    # Structured workout linkage (from Garmin workout definition via wktStepIndex)
    wkt_step_index: Optional[int] = None            # 0-based index into workout steps
    target_pace_slow_s_per_km: Optional[float] = None  # slow boundary of target pace band
    target_pace_fast_s_per_km: Optional[float] = None  # fast boundary of target pace band
    wkt_step_type: Optional[str] = None             # stepTypeKey from workout def, e.g. "recovery", "interval", "other"

    # Relationship
    activity: Optional[Activity] = Relationship(back_populates="splits")
