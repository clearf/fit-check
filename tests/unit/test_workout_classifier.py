"""Tests for WorkoutClassification and classify_from_workout_definition.

Uses the real garmin_workout.json fixture (Speed Repeats workout).
All tests written before implementation (TDD).
"""
import json
import pytest
from pathlib import Path

FIXTURES = Path(__file__).parent.parent / "fixtures"


@pytest.fixture
def speed_workout():
    """Real Garmin workout fixture: 'Speed Repeats'."""
    return json.loads((FIXTURES / "garmin_workout.json").read_text())


from fitness.analysis.workout_classifier import (
    ClassificationMethod,
    WorkoutClassification,
    WorkoutType,
    classify_from_workout_definition,
    classify_workout,
)


# ─── classify_from_workout_definition ────────────────────────────────────────

class TestClassifyFromWorkoutDefinition:
    def test_returns_workout_classification(self, speed_workout):
        result = classify_from_workout_definition(speed_workout)
        assert isinstance(result, WorkoutClassification)

    def test_method_is_structured(self, speed_workout):
        result = classify_from_workout_definition(speed_workout)
        assert result.method == ClassificationMethod.STRUCTURED

    def test_workout_name_preserved(self, speed_workout):
        result = classify_from_workout_definition(speed_workout)
        assert result.workout_name == "Speed Repeats"

    def test_description_preserved(self, speed_workout):
        result = classify_from_workout_definition(speed_workout)
        # The fixture description mentions drills
        assert result.workout_description is not None
        assert len(result.workout_description) > 0

    def test_speed_repeats_classified_as_speed_or_drills(self, speed_workout):
        """The name 'Speed Repeats' should classify as SPEED or DRILLS."""
        result = classify_from_workout_definition(speed_workout)
        assert result.workout_type in (WorkoutType.SPEED, WorkoutType.DRILLS)

    def test_confidence_is_positive(self, speed_workout):
        result = classify_from_workout_definition(speed_workout)
        assert 0.0 < result.confidence <= 1.0

    def test_structured_summary_is_not_empty(self, speed_workout):
        result = classify_from_workout_definition(speed_workout)
        assert result.structured_summary is not None
        assert len(result.structured_summary) > 10

    def test_structured_summary_contains_800m(self, speed_workout):
        """The 800m repeats should appear in the structured summary."""
        result = classify_from_workout_definition(speed_workout)
        assert "800" in result.structured_summary

    def test_structured_summary_contains_repeat_count(self, speed_workout):
        """The ×8 speed repeats should be mentioned."""
        result = classify_from_workout_definition(speed_workout)
        # Should contain something like ×8 or x8 or (8×) or "8 repeats"
        assert "8" in result.structured_summary

    def test_structured_summary_contains_pace_target(self, speed_workout):
        """Pace targets from the pace.zone step should appear."""
        result = classify_from_workout_definition(speed_workout)
        assert "/km" in result.structured_summary

    def test_hill_workout_classified_as_hill(self):
        workout = {
            "workoutId": 999,
            "workoutName": "Hill Repeats",
            "description": "Run up the hill hard.",
            "workoutSegments": [{"workoutSteps": []}],
        }
        result = classify_from_workout_definition(workout)
        assert result.workout_type == WorkoutType.HILL

    def test_easy_run_classified_as_easy(self):
        workout = {
            "workoutId": 998,
            "workoutName": "Easy Run",
            "description": "Easy recovery jog.",
            "workoutSegments": [{"workoutSteps": []}],
        }
        result = classify_from_workout_definition(workout)
        assert result.workout_type == WorkoutType.EASY

    def test_tempo_run_classified_as_race_pace(self):
        workout = {
            "workoutId": 997,
            "workoutName": "Tempo Run",
            "description": "Run at threshold pace.",
            "workoutSegments": [{"workoutSteps": []}],
        }
        result = classify_from_workout_definition(workout)
        assert result.workout_type == WorkoutType.RACE_PACE

    def test_unknown_name_returns_unknown(self):
        workout = {
            "workoutId": 996,
            "workoutName": "My Workout",
            "description": "",
            "workoutSegments": [{"workoutSteps": []}],
        }
        result = classify_from_workout_definition(workout)
        assert result.workout_type == WorkoutType.UNKNOWN

    def test_long_run_classified_as_long_run(self):
        workout = {
            "workoutId": 995,
            "workoutName": "Long Run",
            "description": "Steady aerobic base.",
            "workoutSegments": [{"workoutSteps": []}],
        }
        result = classify_from_workout_definition(workout)
        assert result.workout_type == WorkoutType.LONG_RUN

    def test_drills_in_description_classified_as_drills(self):
        workout = {
            "workoutId": 994,
            "workoutName": "Workout 5",
            "description": "Warm up, cadence drills, acceleration-glider drills, cool down.",
            "workoutSegments": [{"workoutSteps": []}],
        }
        result = classify_from_workout_definition(workout)
        assert result.workout_type == WorkoutType.DRILLS

    def test_speed_in_name_matches_case_insensitive(self):
        workout = {
            "workoutId": 993,
            "workoutName": "SPEED INTERVALS",
            "description": "Sprint reps.",
            "workoutSegments": [{"workoutSteps": []}],
        }
        result = classify_from_workout_definition(workout)
        assert result.workout_type == WorkoutType.SPEED

    def test_reasoning_is_nonempty(self, speed_workout):
        result = classify_from_workout_definition(speed_workout)
        assert result.reasoning is not None
        assert len(result.reasoning) > 0


# ─── classify_workout ─────────────────────────────────────────────────────────

class TestClassifyWorkout:
    def test_returns_none_when_no_workout_json(self):
        """Activity with no workout_definition_json → None."""
        from fitness.models.activity import Activity
        from datetime import datetime
        act = Activity(
            garmin_activity_id="1",
            name="Morning Run",
            activity_type="running",
            start_time_utc=datetime(2026, 2, 18, 8, 0),
            duration_seconds=3600.0,
            distance_meters=10000.0,
            workout_definition_json=None,
        )
        result = classify_workout(act)
        assert result is None

    def test_returns_classification_when_workout_json_present(self, speed_workout):
        """Activity with valid workout JSON → WorkoutClassification."""
        from fitness.models.activity import Activity
        from datetime import datetime
        act = Activity(
            garmin_activity_id="2",
            name="Speed Repeats",
            activity_type="running",
            start_time_utc=datetime(2026, 2, 18, 8, 0),
            duration_seconds=3600.0,
            distance_meters=10000.0,
            workout_definition_json=json.dumps(speed_workout),
        )
        result = classify_workout(act)
        assert result is not None
        assert isinstance(result, WorkoutClassification)

    def test_returns_none_on_invalid_json(self):
        """Activity with malformed workout JSON → None (non-fatal)."""
        from fitness.models.activity import Activity
        from datetime import datetime
        act = Activity(
            garmin_activity_id="3",
            name="Broken",
            activity_type="running",
            start_time_utc=datetime(2026, 2, 18, 8, 0),
            duration_seconds=3600.0,
            distance_meters=10000.0,
            workout_definition_json="NOT VALID JSON {{{",
        )
        result = classify_workout(act)
        assert result is None
