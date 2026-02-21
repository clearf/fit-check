"""
Garmin API response normalizer.

Converts raw dicts from garminconnect into clean field dicts that map
directly onto SQLModel columns. No DB access here — callers (sync_service)
handle persistence.

All functions return plain dicts so they're easy to test without any
SQLModel or DB dependencies.
"""
import json
from datetime import date, datetime
from typing import Any, Dict, Optional


def _parse_garmin_datetime(s: str) -> datetime:
    """Parse Garmin's 'YYYY-MM-DD HH:MM:SS' UTC datetime string."""
    # Garmin uses space-separated, not T, and no timezone suffix
    return datetime.strptime(s.strip(), "%Y-%m-%d %H:%M:%S")


def _pace_from_speed(speed_ms: Optional[float]) -> Optional[float]:
    """Convert m/s to s/km. Returns None if speed is zero or missing."""
    if speed_ms is None or speed_ms <= 0:
        return None
    return 1000.0 / speed_ms


def normalize_activity_summary(raw: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normalize a Garmin activity summary dict into Activity model field dict.

    Args:
        raw: Dict from garminconnect.get_activity(activity_id) or
             the activity object in get_activities() list.

    Returns:
        Dict with keys matching Activity model columns.
    """
    activity_type = raw.get("activityType", {})
    if isinstance(activity_type, dict):
        type_key = activity_type.get("typeKey", "running")
    else:
        type_key = str(activity_type)

    avg_speed = raw.get("averageSpeed")
    avg_pace = _pace_from_speed(avg_speed)

    return {
        "garmin_activity_id": str(raw["activityId"]),
        "name": raw.get("activityName", ""),
        "activity_type": type_key,
        # get_activities() list items use "startTimeGMT"; get_activity_evaluation()
        # detail objects use "startTimeLocal". Prefer GMT (true UTC) when present.
        "start_time_utc": _parse_garmin_datetime(
            raw.get("startTimeGMT") or raw["startTimeLocal"]
        ),
        "duration_seconds": float(raw["duration"]),
        "distance_meters": float(raw["distance"]),
        "avg_hr": raw.get("averageHR"),
        "max_hr": raw.get("maxHR"),
        "avg_pace_seconds_per_km": avg_pace,
        "total_ascent_meters": raw.get("elevationGain"),
        "total_descent_meters": raw.get("elevationLoss"),
        "avg_cadence": raw.get("averageRunningCadenceInStepsPerMinute"),
        "training_effect_aerobic": raw.get("aerobicTrainingEffect"),
        "training_effect_anaerobic": raw.get("anaerobicTrainingEffect"),
        "vo2max_estimated": raw.get("vO2MaxValue"),
        "weather_temp_c": raw.get("weatherTemperature"),
        "raw_summary_json": json.dumps(raw),
    }


def normalize_sleep(raw: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normalize Garmin sleep data into SleepRecord field dict.

    Args:
        raw: Dict from garminconnect.get_sleep_data(date_str).

    Returns:
        Dict with keys matching SleepRecord model columns.
    """
    dto = raw.get("dailySleepDTO", raw)

    # Sleep date from calendarDate string "YYYY-MM-DD"
    cal_date_str = dto.get("calendarDate", "")
    try:
        sleep_date = datetime.strptime(cal_date_str, "%Y-%m-%d").date()
    except ValueError:
        sleep_date = date.today()

    # Sleep score may be nested
    scores = dto.get("sleepScores", {})
    overall = scores.get("overall", {})
    sleep_score = overall.get("value") if isinstance(overall, dict) else overall

    return {
        "sleep_date": sleep_date,
        "duration_seconds": dto.get("sleepTimeSeconds"),
        "deep_sleep_seconds": dto.get("deepSleepSeconds"),
        "light_sleep_seconds": dto.get("lightSleepSeconds"),
        "rem_sleep_seconds": dto.get("remSleepSeconds"),
        "awake_seconds": dto.get("awakeSleepSeconds"),
        "sleep_score": sleep_score,
        "avg_spo2": dto.get("averageSpO2Value"),
        "avg_respiration": dto.get("averageRespirationValue"),
        "raw_json": json.dumps(raw),
    }


def normalize_hrv(raw: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normalize Garmin HRV data into HRVRecord field dict.

    Args:
        raw: Dict from garminconnect.get_hrv_data(date_str).

    Returns:
        Dict with keys matching HRVRecord model columns.
    """
    summary = raw.get("hrvSummary", raw)

    # Parse record date from startTimestampGMT "YYYY-MM-DDTHH:MM:SS"
    start_str = summary.get("startTimestampGMT", "")
    try:
        record_date = datetime.strptime(start_str[:10], "%Y-%m-%d").date()
    except ValueError:
        record_date = date.today()

    return {
        "record_date": record_date,
        "weekly_avg_hrv": summary.get("weeklyAvg"),
        "last_night_avg_hrv": summary.get("lastNight"),
        "last_night_5min_high": summary.get("lastNight5MinHigh"),
        "status": summary.get("status"),
        "raw_json": json.dumps(raw),
    }


def normalize_typed_split(raw: Dict[str, Any], split_index: int) -> Dict[str, Any]:
    """
    Normalize one Garmin typed split into ActivitySplit field dict.

    Args:
        raw: One element from garminconnect.get_activity_typed_splits() list.
        split_index: Position in the original list (used as split_index).

    Returns:
        Dict with keys matching ActivitySplit model columns.
    """
    split_type_raw = str(raw.get("splitType", "")).upper()
    if split_type_raw == "RUN":
        split_type = "run_segment"
    elif split_type_raw == "WALK":
        split_type = "walk_segment"
    else:
        split_type = "lap"

    speed = raw.get("averageSpeed")
    avg_pace = _pace_from_speed(speed)

    return {
        "split_index": split_index,
        "split_type": split_type,
        "start_elapsed_seconds": int(raw.get("startTime", 0)),
        "duration_seconds": float(raw.get("totalElapsedTime", 0)),
        "distance_meters": float(raw.get("totalDistance", 0)),
        "avg_hr": raw.get("averageHR"),
        "avg_pace_seconds_per_km": avg_pace,
        "total_ascent_meters": None,  # not available in typed splits API
    }
