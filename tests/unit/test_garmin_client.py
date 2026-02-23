"""Tests for GarminClient async wrapper.

These tests verify that our wrapper calls the correct garminconnect 0.2.8
method names and signatures. garminconnect 0.2.x made several breaking
changes vs 0.1.x:

  - get_activity()            → removed; use get_activity_evaluation()
  - get_activity_typed_splits() → removed; use get_activity_splits()
  - get_activities(activitytype=) → kwarg removed; filter client-side
  - download_activity()       → default format is TCX; must pass ORIGINAL for FIT
"""
import io
import pytest
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import garminconnect

from fitness.garmin.client import GarminClient


def _make_zip(fit_bytes: bytes, filename: str = "activity_12345.fit") -> bytes:
    """Build an in-memory zip containing one .fit file, as Garmin's ORIGINAL download returns."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(filename, fit_bytes)
    return buf.getvalue()


# ─── Fixtures ─────────────────────────────────────────────────────────────────

FAKE_ACTIVITIES = [
    {"activityId": 1, "activityType": {"typeKey": "running"}, "activityName": "Morning Run"},
    {"activityId": 2, "activityType": {"typeKey": "cycling"}, "activityName": "Bike Ride"},
    {"activityId": 3, "activityType": {"typeKey": "running"}, "activityName": "Evening Run"},
]

FAKE_ACTIVITY_EVAL = {
    "activityId": 12345,
    "activityName": "Morning Run",
    "distance": 8046.72,
    "duration": 3600.0,
}

FAKE_SPLITS = {
    "activityId": 12345,
    "lapDTOs": [
        {"lapIndex": 0, "distance": 1609.34, "averageSpeed": 2.5},
        {"lapIndex": 1, "distance": 1609.34, "averageSpeed": 2.6},
    ],
}

FAKE_SLEEP = {"dailySleepDTO": {"sleepStartTimestampLocal": 1700000000}}
FAKE_HRV = {"hrvSummary": {"lastNight": 55}}

# Garmin's ORIGINAL download returns a zip archive containing the .fit file, not raw FIT bytes.
# FAKE_FIT_BYTES is therefore a zip; all get_fit_datapoints tests must use this.
FAKE_FIT_BYTES = _make_zip(b"FIT_CONTENT_PLACEHOLDER")


@pytest.fixture
def mock_api():
    """A mock garminconnect.Garmin instance with all methods pre-configured."""
    api = MagicMock(spec=garminconnect.Garmin)
    api.get_activities.return_value = FAKE_ACTIVITIES
    api.get_activity_evaluation.return_value = FAKE_ACTIVITY_EVAL
    api.get_activity_splits.return_value = FAKE_SPLITS
    api.get_sleep_data.return_value = FAKE_SLEEP
    api.get_hrv_data.return_value = FAKE_HRV
    api.download_activity.return_value = FAKE_FIT_BYTES
    return api


@pytest.fixture
def connected_client(mock_api):
    """A GarminClient with _api already set (simulates post-connect() state)."""
    client = GarminClient()
    client._api = mock_api
    return client


# ─── Tests: get_activity_summary ─────────────────────────────────────────────

class TestGetActivitySummary:
    async def test_calls_get_activity_evaluation(self, connected_client, mock_api):
        """Must use get_activity_evaluation(), not the removed get_activity()."""
        await connected_client.get_activity_summary("12345")
        mock_api.get_activity_evaluation.assert_called_once_with("12345")

    async def test_get_activity_does_not_exist_on_api(self, mock_api):
        """get_activity() was removed in garminconnect 0.2.8 — confirm it is not on the spec."""
        with pytest.raises(AttributeError):
            _ = mock_api.get_activity  # spec=Garmin enforces this doesn't exist

    async def test_returns_activity_dict(self, connected_client):
        result = await connected_client.get_activity_summary("12345")
        assert result["activityId"] == 12345
        assert result["activityName"] == "Morning Run"

    async def test_passes_activity_id_as_string(self, connected_client, mock_api):
        await connected_client.get_activity_summary("12345")
        args = mock_api.get_activity_evaluation.call_args.args
        assert args[0] == "12345"


# ─── Tests: get_activity_typed_splits ────────────────────────────────────────

class TestGetActivityTypedSplits:
    async def test_calls_get_activity_splits(self, connected_client, mock_api):
        """Must use get_activity_splits(), not the removed get_activity_typed_splits()."""
        await connected_client.get_activity_typed_splits("12345")
        mock_api.get_activity_splits.assert_called_once_with("12345")

    async def test_get_activity_typed_splits_does_not_exist_on_api(self, mock_api):
        """get_activity_typed_splits() was removed in garminconnect 0.2.8 — confirm absent."""
        with pytest.raises(AttributeError):
            _ = mock_api.get_activity_typed_splits  # spec=Garmin enforces this doesn't exist

    async def test_returns_list(self, connected_client):
        result = await connected_client.get_activity_typed_splits("12345")
        assert isinstance(result, list)

    async def test_returns_lap_dtos_from_dict_response(self, connected_client, mock_api):
        """When API returns a dict, extract the lapDTOs list."""
        mock_api.get_activity_splits.return_value = {
            "activityId": 12345,
            "lapDTOs": [{"lapIndex": 0}, {"lapIndex": 1}],
        }
        result = await connected_client.get_activity_typed_splits("12345")
        assert len(result) == 2
        assert result[0]["lapIndex"] == 0

    async def test_returns_list_directly_when_api_returns_list(self, connected_client, mock_api):
        """When API returns a list directly, return it as-is."""
        mock_api.get_activity_splits.return_value = [{"lapIndex": 0}]
        result = await connected_client.get_activity_typed_splits("12345")
        assert result == [{"lapIndex": 0}]

    async def test_returns_empty_list_when_no_laps(self, connected_client, mock_api):
        """Returns empty list if dict response has no lapDTOs key."""
        mock_api.get_activity_splits.return_value = {"activityId": 12345}
        result = await connected_client.get_activity_typed_splits("12345")
        assert result == []


# ─── Tests: get_sleep_data ────────────────────────────────────────────────────

class TestGetSleepData:
    async def test_calls_get_sleep_data(self, connected_client, mock_api):
        await connected_client.get_sleep_data("2024-01-15")
        mock_api.get_sleep_data.assert_called_once_with("2024-01-15")

    async def test_returns_sleep_dict(self, connected_client):
        result = await connected_client.get_sleep_data("2024-01-15")
        assert "dailySleepDTO" in result

    async def test_passes_date_string(self, connected_client, mock_api):
        await connected_client.get_sleep_data("2024-06-01")
        args = mock_api.get_sleep_data.call_args.args
        assert args[0] == "2024-06-01"


# ─── Tests: get_hrv_data ─────────────────────────────────────────────────────

class TestGetHrvData:
    async def test_calls_get_hrv_data(self, connected_client, mock_api):
        await connected_client.get_hrv_data("2024-01-15")
        mock_api.get_hrv_data.assert_called_once_with("2024-01-15")

    async def test_returns_hrv_dict(self, connected_client):
        result = await connected_client.get_hrv_data("2024-01-15")
        assert "hrvSummary" in result

    async def test_passes_date_string(self, connected_client, mock_api):
        await connected_client.get_hrv_data("2024-06-01")
        args = mock_api.get_hrv_data.call_args.args
        assert args[0] == "2024-06-01"


# ─── Tests: get_activities ────────────────────────────────────────────────────

class TestGetActivities:
    async def test_calls_api_with_start_and_limit(self, connected_client, mock_api):
        await connected_client.get_activities(start=0, limit=10)
        mock_api.get_activities.assert_called_once_with(0, 10)

    async def test_does_not_pass_activitytype_kwarg(self, connected_client, mock_api):
        """garminconnect 0.2.8 removed the activitytype kwarg — must not be passed."""
        await connected_client.get_activities(start=0, limit=5)
        call_kwargs = mock_api.get_activities.call_args.kwargs
        assert "activitytype" not in call_kwargs

    async def test_filters_by_activity_type(self, connected_client):
        result = await connected_client.get_activities(start=0, limit=20, activity_type="running")
        type_keys = [a["activityType"]["typeKey"] for a in result]
        assert all(t == "running" for t in type_keys)

    async def test_filters_out_non_matching_types(self, connected_client):
        result = await connected_client.get_activities(start=0, limit=20, activity_type="running")
        ids = [a["activityId"] for a in result]
        assert 2 not in ids  # cycling activity should be excluded

    async def test_returns_all_when_activity_type_is_none(self, connected_client):
        result = await connected_client.get_activities(start=0, limit=20, activity_type=None)
        assert len(result) == len(FAKE_ACTIVITIES)

    async def test_default_activity_type_is_running(self, connected_client):
        result = await connected_client.get_activities(start=0, limit=20)
        type_keys = [a["activityType"]["typeKey"] for a in result]
        assert all(t == "running" for t in type_keys)

    async def test_returns_empty_list_when_no_matches(self, connected_client):
        result = await connected_client.get_activities(start=0, limit=20, activity_type="swimming")
        assert result == []

    async def test_uses_default_start_and_limit(self, connected_client, mock_api):
        await connected_client.get_activities()
        mock_api.get_activities.assert_called_once_with(0, 20)

    async def test_returns_list(self, connected_client):
        result = await connected_client.get_activities(start=0, limit=20)
        assert isinstance(result, list)


# ─── Tests: get_fit_datapoints ────────────────────────────────────────────────

class TestGetFitDatapoints:
    async def test_calls_download_activity_with_original_format(self, connected_client, mock_api):
        """Must pass ActivityDownloadFormat.ORIGINAL to get FIT bytes, not the default TCX."""
        with patch("fitness.garmin.client.parse_fit_file", return_value=[]):
            await connected_client.get_fit_datapoints("12345")

        mock_api.download_activity.assert_called_once_with(
            "12345",
            dl_fmt=garminconnect.Garmin.ActivityDownloadFormat.ORIGINAL,
        )

    async def test_does_not_use_default_tcx_format(self, connected_client, mock_api):
        """Calling download_activity with no dl_fmt gives TCX, not FIT — must always pass ORIGINAL."""
        with patch("fitness.garmin.client.parse_fit_file", return_value=[]):
            await connected_client.get_fit_datapoints("12345")

        call_kwargs = mock_api.download_activity.call_args.kwargs
        assert "dl_fmt" in call_kwargs, "dl_fmt must be explicitly passed"
        assert call_kwargs["dl_fmt"] == garminconnect.Garmin.ActivityDownloadFormat.ORIGINAL

    async def test_passes_activity_id_as_string(self, connected_client, mock_api):
        with patch("fitness.garmin.client.parse_fit_file", return_value=[]):
            await connected_client.get_fit_datapoints("12345")
        args = mock_api.download_activity.call_args.args
        assert args[0] == "12345"

    async def test_returns_parsed_datapoints(self, connected_client, mock_api):
        fake_points = [{"timestamp": "2024-01-01T08:00:00", "heart_rate": 150}]
        with patch("fitness.garmin.client.parse_fit_file", return_value=fake_points):
            result = await connected_client.get_fit_datapoints("12345")
        assert result == fake_points

    async def test_cleans_up_temp_file_on_success(self, connected_client, mock_api):
        """Temp file must be deleted after successful parse."""
        created_paths = []

        original_parse = __import__("fitness.garmin.fit_parser", fromlist=["parse_fit_file"]).parse_fit_file

        def capture_path(path):
            created_paths.append(path)
            return []

        with patch("fitness.garmin.client.parse_fit_file", side_effect=capture_path):
            await connected_client.get_fit_datapoints("12345")

        assert len(created_paths) == 1
        assert not created_paths[0].exists(), "Temp file should be deleted after parsing"

    async def test_cleans_up_temp_file_on_parse_error(self, connected_client, mock_api):
        """Temp file must be deleted even if parse_fit_file raises."""
        created_paths = []

        def capture_and_raise(path):
            created_paths.append(path)
            raise ValueError("Bad FIT file")

        with patch("fitness.garmin.client.parse_fit_file", side_effect=capture_and_raise):
            with pytest.raises(ValueError, match="Bad FIT file"):
                await connected_client.get_fit_datapoints("12345")

        assert len(created_paths) == 1
        assert not created_paths[0].exists(), "Temp file should be deleted even on error"

    async def test_returns_list(self, connected_client):
        with patch("fitness.garmin.client.parse_fit_file", return_value=[]):
            result = await connected_client.get_fit_datapoints("12345")
        assert isinstance(result, list)

    async def test_unzips_before_writing_fit_file(self, connected_client, mock_api):
        """Regression: ORIGINAL download returns a zip, not raw FIT bytes.

        parse_fit_file must receive the extracted .fit content, not the zip bytes.
        Without the unzip step this raises: FitParseError: Invalid .FIT File Header.
        """
        sentinel_fit_bytes = b"\x0eFIT_SENTINEL_CONTENT_XYZZY"
        mock_api.download_activity.return_value = _make_zip(sentinel_fit_bytes)

        written_bytes = []

        def capture_written(path: Path):
            written_bytes.append(path.read_bytes())
            return []

        with patch("fitness.garmin.client.parse_fit_file", side_effect=capture_written):
            await connected_client.get_fit_datapoints("12345")

        assert len(written_bytes) == 1
        assert written_bytes[0] == sentinel_fit_bytes, (
            "parse_fit_file received zip bytes instead of extracted .fit content — "
            "unzip step is missing or broken"
        )

    async def test_raises_if_zip_has_no_fit_file(self, connected_client, mock_api):
        """If the zip contains no .fit member, a clear ValueError is raised."""
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("notes.txt", b"no fit here")
        mock_api.download_activity.return_value = buf.getvalue()

        with pytest.raises(ValueError, match="No .fit file found"):
            await connected_client.get_fit_datapoints("12345")

    async def test_raises_if_download_is_not_a_zip(self, connected_client, mock_api):
        """If Garmin returns non-zip bytes (e.g. TCX XML), a clear error is raised."""
        mock_api.download_activity.return_value = b"<TrainingCenterDatabase>...</TrainingCenterDatabase>"

        with pytest.raises(Exception):
            await connected_client.get_fit_datapoints("12345")


# ─── Tests: get_workout ───────────────────────────────────────────────────────

FAKE_WORKOUT = {
    "workoutId": 1467965958,
    "workoutName": "Speed Repeats",
    "description": "Warm up, speed reps, cool down.",
    "workoutSegments": [],
}


class TestGetWorkout:
    async def test_calls_connectapi_with_correct_path(self, connected_client, mock_api):
        """Must use connectapi() — garminconnect has no get_workout() method."""
        mock_api.connectapi = MagicMock(return_value=FAKE_WORKOUT)
        await connected_client.get_workout(1467965958)
        mock_api.connectapi.assert_called_once_with(
            "/workout-service/workout/1467965958"
        )

    async def test_accepts_int_workout_id(self, connected_client, mock_api):
        """workout_id is an int; must be interpolated as int in URL path."""
        mock_api.connectapi = MagicMock(return_value=FAKE_WORKOUT)
        await connected_client.get_workout(1467965958)
        call_args = mock_api.connectapi.call_args.args[0]
        assert "1467965958" in call_args

    async def test_returns_workout_dict(self, connected_client, mock_api):
        """Returns the raw dict from the Garmin workout service."""
        mock_api.connectapi = MagicMock(return_value=FAKE_WORKOUT)
        result = await connected_client.get_workout(1467965958)
        assert result["workoutId"] == 1467965958
        assert result["workoutName"] == "Speed Repeats"

    async def test_returns_description(self, connected_client, mock_api):
        """Description field is preserved in the returned dict."""
        mock_api.connectapi = MagicMock(return_value=FAKE_WORKOUT)
        result = await connected_client.get_workout(1467965958)
        assert "description" in result
