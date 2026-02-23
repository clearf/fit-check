"""
Workout type classification from Garmin structured workout definitions.

Given a workout_definition_json (from Activity.workout_definition_json, originally
fetched from /workout-service/workout/{id}), classifies the session into a
high-level workout type and generates a human-readable structured summary of
the planned steps.

Only the structured classification path is implemented. Heuristic fallback for
unstructured runs is deliberately deferred.

Public API:
  classify_workout(activity)  → Optional[WorkoutClassification]
  classify_from_workout_definition(workout_def) → WorkoutClassification

WorkoutType enum:
  SPEED       — speed intervals / track repeats (800m, 400m, mile, etc.)
  HILL        — hill repeats
  RACE_PACE   — tempo / lactate threshold / race-pace work
  LONG_RUN    — aerobic base builder
  EASY        — easy / recovery
  DRILLS      — cadence / form / acceleration-glider drills
  UNKNOWN     — none of the above matched
"""
import json
import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional

from fitness.garmin.normalizer import _collect_all_steps, _parse_step_targets


class WorkoutType(str, Enum):
    SPEED = "speed"
    HILL = "hill"
    RACE_PACE = "race_pace"
    LONG_RUN = "long_run"
    EASY = "easy"
    DRILLS = "drills"
    UNKNOWN = "unknown"


class ClassificationMethod(str, Enum):
    STRUCTURED = "structured"


@dataclass
class WorkoutClassification:
    """Classification result for one workout."""
    workout_type: WorkoutType
    method: ClassificationMethod
    confidence: float          # 0.0–1.0
    reasoning: str
    workout_name: Optional[str] = None
    workout_description: Optional[str] = None  # raw Garmin description field
    structured_summary: Optional[str] = None   # human-readable step structure


# Keyword rules applied (in priority order) to the combined name + description text.
# The first match wins.
_KEYWORD_RULES: List[tuple] = [
    (WorkoutType.HILL,      re.compile(r"\bhills?\b|\bhill\s+repeat", re.I)),
    (WorkoutType.LONG_RUN,  re.compile(r"\blong.?run\b|\blr\b", re.I)),
    (WorkoutType.SPEED,     re.compile(r"\bspeed\b|\binterval|\b800\s*m?\b|\b400\s*m?\b|\b1200\s*m?\b|\b1600\s*m?\b", re.I)),
    (WorkoutType.RACE_PACE, re.compile(r"\btempo\b|\blactate\b|\bthreshold\b|\brace.?pace\b|\b\bmp\b", re.I)),
    (WorkoutType.EASY,      re.compile(r"\beasy\b|\brecovery\s+run\b|\bjog\b", re.I)),
    (WorkoutType.DRILLS,    re.compile(r"\bdrills?\b|\bcadence\b|\bstrides?\b|\bglider\b|\bacceleration\b", re.I)),
]


def _format_duration(seconds: Optional[float]) -> str:
    """Format seconds as M:SS or as distance string."""
    if seconds is None:
        return ""
    s = int(seconds)
    return f"{s // 60}:{s % 60:02d}"


def _format_pace(s_per_km: Optional[float]) -> str:
    """Format s/km as M:SS/km."""
    if s_per_km is None:
        return ""
    s = int(s_per_km)
    return f"{s // 60}:{s % 60:02d}/km"


def _build_structured_summary(workout_def: Dict[str, Any]) -> str:
    """
    Build a human-readable multi-line summary of the workout's planned steps.

    RepeatGroups are shown as "Description ×N: condition | target".
    Standalone steps are shown with their condition and target.
    """
    lines = []
    segments = workout_def.get("workoutSegments", [])

    for segment in segments:
        steps = segment.get("workoutSteps", [])
        for step in steps:
            _summarize_step(step, lines, indent=0)

    return "\n".join(lines) if lines else "(no steps)"


def _summarize_step(step: Dict[str, Any], lines: List[str], indent: int) -> None:
    """Recursively add summary lines for a step or repeat group."""
    prefix = "  " * indent

    if step.get("type") == "RepeatGroupDTO":
        n = step.get("numberOfIterations", 1)
        child_steps = step.get("workoutSteps", [])
        # Summarise each child under the group
        for child in child_steps:
            child_lines: List[str] = []
            _summarize_step(child, child_lines, indent=0)
            for cl in child_lines:
                # Prefix with ×N
                lines.append(f"{prefix}{cl} ×{n}" if "×" not in cl else f"{prefix}{cl}")
        return

    # ExecutableStepDTO
    targets = _parse_step_targets(step)
    step_type = targets.get("step_type_key", "")
    description = step.get("description") or step_type.capitalize()
    end_cond = targets.get("end_condition_key", "")
    end_val = targets.get("end_condition_value")

    # Condition string
    if end_cond == "distance" and end_val:
        cond_str = f"{int(end_val)}m" if end_val >= 100 else f"{end_val:.0f}m"
    elif end_cond == "time" and end_val:
        cond_str = _format_duration(end_val)
    elif end_cond == "lap.button":
        cond_str = "lap button"
    elif end_cond == "iterations":
        cond_str = "repeats"
    else:
        cond_str = ""

    # Target string
    pace_slow = targets.get("target_pace_slow_s_per_km")
    pace_fast = targets.get("target_pace_fast_s_per_km")
    cad_low = targets.get("target_cadence_low")
    cad_high = targets.get("target_cadence_high")

    if pace_slow is not None and pace_fast is not None:
        target_str = f"target pace {_format_pace(pace_fast)}–{_format_pace(pace_slow)}"
    elif cad_low is not None and cad_high is not None:
        target_str = f"target cadence {int(cad_low)}–{int(cad_high)} spm"
    else:
        target_str = "no target"

    parts = [description]
    if cond_str:
        parts.append(cond_str)
    parts.append(f"| {target_str}")

    lines.append(f"{prefix}" + " ".join(parts))


def classify_from_workout_definition(workout_def: Dict[str, Any]) -> WorkoutClassification:
    """
    Classify a structured Garmin workout into a WorkoutType.

    Applies keyword rules to both workout name and description.
    The first matching rule wins (rules are ordered by priority).
    Confidence is 0.85 for a name match, 0.70 for a description-only match,
    0.50 if neither text matched (fallback to UNKNOWN).

    Args:
        workout_def: Raw dict from GET /workout-service/workout/{id}.

    Returns:
        WorkoutClassification with type, confidence, reasoning, and summary.
    """
    name = workout_def.get("workoutName") or ""
    description = workout_def.get("description") or ""

    workout_type = WorkoutType.UNKNOWN
    confidence = 0.50
    reasoning = "No keyword matched in name or description."
    match_field = ""

    # Check name first (higher confidence), then description
    for wtype, pattern in _KEYWORD_RULES:
        if pattern.search(name):
            workout_type = wtype
            confidence = 0.85
            reasoning = f"Keyword matched in workout name: '{pattern.pattern}'"
            match_field = "name"
            break

    if workout_type == WorkoutType.UNKNOWN:
        for wtype, pattern in _KEYWORD_RULES:
            if pattern.search(description):
                workout_type = wtype
                confidence = 0.70
                reasoning = f"Keyword matched in description: '{pattern.pattern}'"
                match_field = "description"
                break

    structured_summary = _build_structured_summary(workout_def)

    return WorkoutClassification(
        workout_type=workout_type,
        method=ClassificationMethod.STRUCTURED,
        confidence=confidence,
        reasoning=reasoning,
        workout_name=name or None,
        workout_description=description or None,
        structured_summary=structured_summary,
    )


def classify_workout(activity) -> Optional[WorkoutClassification]:
    """
    Classify the workout associated with an Activity.

    Returns None if the activity has no workout definition or if parsing fails.
    This is always non-fatal.

    Args:
        activity: Activity model instance (must have workout_definition_json attr).

    Returns:
        WorkoutClassification or None.
    """
    if not activity.workout_definition_json:
        return None
    try:
        workout_def = json.loads(activity.workout_definition_json)
        return classify_from_workout_definition(workout_def)
    except (json.JSONDecodeError, KeyError, TypeError):
        return None
