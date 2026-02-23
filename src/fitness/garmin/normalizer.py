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
        "wkt_step_index": raw.get("wktStepIndex"),
    }


def _collect_all_steps(steps: list) -> list:
    """
    Collect ALL steps (both container and executable) for step target mapping.

    Garmin workout definitions have two step types:
      - ExecutableStepDTO: a real step (warmup, interval, recovery, etc.)
      - RepeatGroupDTO: a loop container with nested workoutSteps

    IMPORTANT: The wktStepIndex in lapDTOs maps to the RepeatGroupDTO container's
    stepOrder (not the executable child's stepOrder). For example, if a cadence
    drill is at stepOrder=4 inside a RepeatGroup at stepOrder=3, laps will show
    wktStepIndex=2 (= stepOrder=3 - 1), referring to the group, not the child.

    Strategy: include ALL steps (containers and executables) in the flat list.
    RepeatGroupDTO containers use the first child's target info (since the group
    itself has no target — the target belongs to the interval step inside it).

    Args:
        steps: List of raw step dicts from workoutSegments[*].workoutSteps.

    Returns:
        Flat list of all step dicts, with RepeatGroupDTOs replaced by a synthetic
        entry carrying the first child's target info and the group's own stepOrder.
    """
    flat = []
    for step in steps:
        if step.get("type") == "RepeatGroupDTO":
            # The RepeatGroup container itself occupies a stepOrder slot and
            # maps to a wktStepIndex in the lap data. We represent it using
            # a synthetic entry derived from the first executable child's targets.
            child_steps = step.get("workoutSteps", [])
            first_executable = next(
                (s for s in child_steps if s.get("type") != "RepeatGroupDTO"),
                None
            )
            if first_executable is not None:
                # Synthetic entry: group's stepOrder + first child's target info
                synthetic = dict(first_executable)
                synthetic["stepOrder"] = step["stepOrder"]
                flat.append(synthetic)
            # Also recurse into children (they each have their own stepOrders)
            flat.extend(_collect_all_steps(child_steps))
        else:
            flat.append(step)
    return flat


def _parse_step_targets(step: Dict[str, Any]) -> Dict[str, Any]:
    """
    Extract target values from a single ExecutableStepDTO.

    Returns a dict with keys:
      target_pace_slow_s_per_km  — slow-end pace in s/km (None if not pace target)
      target_pace_fast_s_per_km  — fast-end pace in s/km (None if not pace target)
      target_cadence_low         — low cadence in spm (None if not cadence target)
      target_cadence_high        — high cadence in spm (None if not cadence target)
      step_type_key              — e.g. "warmup", "interval", "recovery", "cooldown"
      end_condition_key          — e.g. "time", "distance", "lap.button"
      end_condition_value        — seconds (time) or metres (distance), or None
      description                — step description text, or None
    """
    target_type = step.get("targetType") or {}
    target_key = target_type.get("workoutTargetTypeKey", "") if isinstance(target_type, dict) else ""

    step_type = step.get("stepType") or {}
    step_type_key = step_type.get("stepTypeKey", "") if isinstance(step_type, dict) else ""

    end_cond = step.get("endCondition") or {}
    end_cond_key = end_cond.get("conditionTypeKey", "") if isinstance(end_cond, dict) else ""

    val_one = step.get("targetValueOne")
    val_two = step.get("targetValueTwo")

    if target_key == "pace.zone":
        # Garmin API: targetValueOne = faster m/s (e.g. 3.538 m/s → 4:42/km)
        #             targetValueTwo = slower m/s (e.g. 3.389 m/s → 4:55/km)
        # Column convention: slow_s_per_km > fast_s_per_km (more s/km = slower pace)
        pace_fast = _pace_from_speed(val_one)  # faster m/s → fewer s/km = fast end
        pace_slow = _pace_from_speed(val_two)  # slower m/s → more s/km = slow end
        cadence_low = None
        cadence_high = None
    elif target_key == "cadence":
        pace_slow = None
        pace_fast = None
        cadence_low = val_one
        cadence_high = val_two
    else:
        pace_slow = None
        pace_fast = None
        cadence_low = None
        cadence_high = None

    return {
        "target_pace_slow_s_per_km": pace_slow,
        "target_pace_fast_s_per_km": pace_fast,
        "target_cadence_low": cadence_low,
        "target_cadence_high": cadence_high,
        "step_type_key": step_type_key,
        "end_condition_key": end_cond_key,
        "end_condition_value": step.get("endConditionValue"),
        "description": step.get("description"),
    }


def build_step_target_map(workout_def: Dict[str, Any]) -> Dict[int, Dict[str, Any]]:
    """
    Build a lookup map from wktStepIndex → step target info.

    Garmin's wktStepIndex on lapDTOs is 0-based; workout step stepOrder is
    1-based. The mapping is: wktStepIndex = stepOrder - 1.

    RepeatGroupDTO container steps occupy stepOrder slots but do not generate
    laps, so gaps in wktStepIndex are expected (e.g. 0,1,2,3,5,6,8,9,10,12).
    Only ExecutableStepDTO entries are included in the map.

    Args:
        workout_def: Raw dict from GET /workout-service/workout/{id}.

    Returns:
        Dict keyed by wktStepIndex (int), values are dicts from _parse_step_targets().
        Returns empty dict if workout_def has no segments or steps.
    """
    result: Dict[int, Dict[str, Any]] = {}
    segments = workout_def.get("workoutSegments", [])
    for segment in segments:
        steps = segment.get("workoutSteps", [])
        for step in _collect_all_steps(steps):
            step_order = step.get("stepOrder")
            if step_order is not None:
                wkt_idx = step_order - 1  # convert 1-based stepOrder to 0-based wktStepIndex
                result[wkt_idx] = _parse_step_targets(step)
    return result
