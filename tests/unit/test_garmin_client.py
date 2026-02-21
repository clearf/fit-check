"""Tests for GarminClient async wrapper."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from fitness.garmin.client import GarminClient
from fitness.garmin.auth import GarminAuth


# ─── Fixtures ─────────────────────────────────────────────────────────────────

FAKE_ACTIVITIES = [
    {"activityId": 1, "activityType": {"typeKey": "running"}, "activityName": "Morning Run"},
    {"activityId": 2, "activityType": {"typeKey": "cycling"}, "activityName": "Bike Ride"},
    {"activityId": 3, "activityType": {"typeKey": "running"}, "activityName": "Evening Run"},
]


@pytest.fixture
def mock_api():
    """A mock garminconnect.Garmin instance."""
    api = MagicMock()
    api.get_activities.return_value = FAKE_ACTIVITIES
    return api


@pytest.fixture
def connected_client(mock_api):
    """A GarminClient with _api already set (simulates post-connect() state)."""
    client = GarminClient()
    client._api = mock_api
    return client


# ─── Tests: get_activities ────────────────────────────────────────────────────

class TestGetActivities:
    async def test_calls_api_with_start_and_limit(self, connected_client, mock_api):
        await connected_client.get_activities(start=0, limit=10)
        mock_api.get_activities.assert_called_once_with(0, 10)

    async def test_does_not_pass_activitytype_kwarg(self, connected_client, mock_api):
        """garminconnect 0.2.8 removed the activitytype kwarg — must not be passed."""
        await connected_client.get_activities(start=0, limit=5)
        call_kwargs = mock_api.get_activities.call_args.kwargs
        assert "activitytype" not in call_kwargs, (
            "activitytype kwarg must not be passed to garminconnect 0.2.8 get_activities()"
        )

    async def test_filters_by_activity_type(self, connected_client):
        """Only activities matching the requested type should be returned."""
        result = await connected_client.get_activities(start=0, limit=20, activity_type="running")
        type_keys = [a["activityType"]["typeKey"] for a in result]
        assert all(t == "running" for t in type_keys)

    async def test_filters_out_non_matching_types(self, connected_client):
        """Activities with a different type key should be excluded."""
        result = await connected_client.get_activities(start=0, limit=20, activity_type="running")
        ids = [a["activityId"] for a in result]
        assert 2 not in ids  # cycling activity should be excluded

    async def test_returns_all_activities_when_no_type_filter(self, connected_client):
        """Passing activity_type=None should return all activities unfiltered."""
        result = await connected_client.get_activities(start=0, limit=20, activity_type=None)
        assert len(result) == len(FAKE_ACTIVITIES)

    async def test_default_activity_type_is_running(self, connected_client):
        """Default activity_type should filter to running activities."""
        result = await connected_client.get_activities(start=0, limit=20)
        type_keys = [a["activityType"]["typeKey"] for a in result]
        assert all(t == "running" for t in type_keys)

    async def test_returns_empty_list_when_no_matches(self, connected_client):
        """Returns empty list if no activities match the requested type."""
        result = await connected_client.get_activities(start=0, limit=20, activity_type="swimming")
        assert result == []

    async def test_uses_default_start_and_limit(self, connected_client, mock_api):
        await connected_client.get_activities()
        mock_api.get_activities.assert_called_once_with(0, 20)

    async def test_returns_list(self, connected_client):
        result = await connected_client.get_activities(start=0, limit=20)
        assert isinstance(result, list)
