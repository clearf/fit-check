"""
Garmin API response normalizer.

Converts raw dicts from garminconnect into clean field dicts that map
directly onto SQLModel columns. No DB access here — callers (sync_service)
handle persistence.

All functions return plain dicts so they're easy to test without any
SQLModel or DB dependencies.

Garmin uses two different response schemas depending on the endpoint:

  get_activities() list items:
    - Flat structure: activityType, startTimeGMT, startTimeLocal at top level
    - Time format: "YYYY-MM-DD HH:MM:SS" (space-separated, no timezone suffix)

  get_activity_evaluation() detail objects:
    - Nested structure: summaryDTO contains performance fields, activityTypeDTO
      contains type info, time keys at top level are absent
    - Time format: "YYYY-MM-DDTHH:MM:SS.f" (ISO 8601 with T separator)

Both schemas are handled transparently by normalize_activity_summary().
"""
import json
from datetime import date, datetime
from typing import Any, Dict, Optional


def _parse_garmin_datetime(s: str) -> datetime:
    """Parse Garmin datetime strings from either endpoint format.

    Handles two formats:
      - "YYYY-MM-DD HH:MM:SS"          (get_activities list items)
      - "YYYY-MM-DDTHH:MM:SS.f"        (get_activity_evaluation detail)
    """
    s = s.strip()
    # ISO 8601 with T separator (evaluation endpoint)
    if "T" in s:
        # Normalize fractional seconds: may be .0, .00, etc.
        base = s.split(".")[0]  # drop fractional seconds
        return datetime.strptime(base, "%Y-%m-%dT%H:%M:%S")
    # Space-separated (list endpoint)
    return datetime.strptime(s, "%Y-%m-%d %H:%M:%S")


def _pace_from_speed(speed_ms: Optional[float]) -> Optional[float]:
    """Convert m/s to s/km. Returns None if speed is zero or missing."""
    if speed_ms is None or speed_ms <= 0:
        return None
    return 1000.0 / speed_ms


def normalize_activity_summary(raw: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normalize a Garmin activity summary dict into Activity model field dict.

    Handles two source schemas transparently:

    1. get_activities() list items (flat schema):
       - activityType: {"typeKey": "running"}  at top level
       - startTimeGMT, startTimeLocal          at top level
       - averageHR, maxHR, distance, duration  at top level

    2. get_activity_evaluation() detail objects (nested schema):
       - activityTypeDTO: {"typeKey": "running"}  at top level
       - summaryDTO.startTimeGMT / startTimeLocal nested
       - summaryDTO.averageHR, distance, duration  nested

    Args:
        raw: Dict from either garminconnect endpoint.

    Returns:
        Dict with keys matching Activity model columns.
    """
    # ── Activity type ──────────────────────────────────────────────────────────
    # get_activities()        → "activityType": {"typeKey": "running"}
    # get_activity_evaluation() → "activityTypeDTO": {"typeKey": "running"}
    activity_type = raw.get("activityType") or raw.get("activityTypeDTO", {})
    if isinstance(activity_type, dict):
        type_key = activity_type.get("typeKey", "running")
    else:
        type_key = str(activity_type)

    # ── Performance fields: flat vs nested ────────────────────────────────────
    # get_activity_evaluation() nests most fields under summaryDTO.
    # Fall back to top-level if summaryDTO absent (get_activities list items).
    summary = raw.get("summaryDTO", raw)

    # ── Start time ────────────────────────────────────────────────────────────
    # Prefer true UTC (GMT) when available; fall back to local timestamp.
    # get_activities() has both keys at top level.
    # get_activity_evaluation() has both inside summaryDTO.
    time_str = (
        raw.get("startTimeGMT")
        or summary.get("startTimeGMT")
        or raw.get("startTimeLocal")
        or summary.get("startTimeLocal")
    )
    if time_str is None:
        raise KeyError(
            "Neither 'startTimeGMT' nor 'startTimeLocal' found in activity response. "
            "Keys present: " + str(list(raw.keys()))
        )

    avg_speed = summary.get("averageSpeed") or raw.get("averageSpeed")
    avg_pace = _pace_from_speed(avg_speed)

    return {
        "garmin_activity_id": str(raw["activityId"]),
        "name": raw.get("activityName", ""),
        "activity_type": type_key,
        "start_time_utc": _parse_garmin_datetime(time_str),
        "duration_seconds": float(
            summary.get("duration") if summary.get("duration") is not None
            else raw["duration"]
        ),
        "distance_meters": float(
            summary.get("distance") if summary.get("distance") is not None
            else raw["distance"]
        ),
        "avg_hr": summary.get("averageHR") or raw.get("averageHR"),
        "max_hr": summary.get("maxHR") or raw.get("maxHR"),
        "avg_pace_seconds_per_km": avg_pace,
        "total_ascent_meters": summary.get("elevationGain") or raw.get("elevationGain"),
        "total_descent_meters": summary.get("elevationLoss") or raw.get("elevationLoss"),
        # cadence field name differs by endpoint
        "avg_cadence": (
            summary.get("averageRunCadence")
            or raw.get("averageRunCadence")
            or raw.get("averageRunningCadenceInStepsPerMinute")
        ),
        # trainingEffect in summaryDTO; aerobicTrainingEffect in list items
        "training_effect_aerobic": (
            summary.get("trainingEffect")
            or raw.get("aerobicTrainingEffect")
        ),
        "training_effect_anaerobic": (
            summary.get("anaerobicTrainingEffect")
            or raw.get("anaerobicTrainingEffect")
        ),
        # vO2MaxValue is only in get_activities() list items, not evaluation
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
    if isinstance(scores, dict):
        overall = scores.get("overall", {})
        sleep_score = overall.get("value") if isinstance(overall, dict) else overall
    else:
        sleep_score = None

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
    Normalize one Garmin lap/split into ActivitySplit field dict.

    Handles lapDTOs from get_activity_splits():
      - intensityType: "ACTIVE", "RECOVERY", "WARMUP", "COOLDOWN"
      - distance, duration (elapsed), averageHR, averageSpeed at top level
      - startTimeGMT: ISO 8601 timestamp (start time of this lap)

    Args:
        raw: One lapDTO element from get_activity_splits()["lapDTOs"].
        split_index: Position in the original list (used as split_index).

    Returns:
        Dict with keys matching ActivitySplit model columns.
    """
    # Map intensityType → split_type string
    # Preserve WARMUP/COOLDOWN as distinct types so the segment labeler can
    # assign "Warmup" / "Cooldown" labels without relying on distance heuristics.
    intensity = str(raw.get("intensityType", "")).upper()
    if intensity == "ACTIVE":
        split_type = "run_segment"
    elif intensity == "RECOVERY":
        split_type = "walk_segment"
    elif intensity == "WARMUP":
        split_type = "warmup_segment"
    elif intensity == "COOLDOWN":
        split_type = "cooldown_segment"
    else:
        split_type = "lap"

    speed = raw.get("averageSpeed")
    avg_pace = _pace_from_speed(speed)

    # start_elapsed_seconds: derived from startTimeGMT relative to activity start
    # Callers that know the activity start time can compute this; here we store
    # the raw value as provided (0 if unknown).
    start_elapsed = int(raw.get("startTime", raw.get("start_elapsed_seconds", 0)))

    return {
        "split_index": split_index,
        "split_type": split_type,
        "start_elapsed_seconds": start_elapsed,
        "duration_seconds": float(raw.get("duration") or raw.get("totalElapsedTime") or 0),
        "distance_meters": float(raw.get("distance") or raw.get("totalDistance") or 0),
        "avg_hr": raw.get("averageHR"),
        "avg_pace_seconds_per_km": avg_pace,
        "total_ascent_meters": raw.get("elevationGain"),
    }
