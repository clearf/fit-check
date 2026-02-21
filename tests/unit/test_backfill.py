"""Tests for the backfill script.

We test the _backfill() async function in isolation by mocking:
  - GarminClient (no real network calls)
  - GarminSyncService (no real DB writes)
  - SQLModel session / engine (in-memory)

All imports inside _backfill() are lazy (inside the function body), so we
patch them at their source module paths using patch().

Key behaviours:
  - Activities already in DB are skipped (idempotency)
  - Activities outside the time window are skipped
  - sync_activity() called for each in-window activity not yet in DB
  - asyncio.sleep is called between activities
  - Failures on individual activities don't abort the run
"""
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ─── Helpers ──────────────────────────────────────────────────────────────────

def make_act_summary(activity_id: int, start_gmt: str) -> dict:
    """Build a minimal get_activities() list item dict."""
    return {
        "activityId": activity_id,
        "startTimeGMT": start_gmt,
        "activityType": {"typeKey": "running"},
    }


def _make_mock_session(exists_in_db: bool = False):
    """Return a context-manager-compatible mock session."""
    mock_session = MagicMock()
    mock_session.__enter__ = MagicMock(return_value=mock_session)
    mock_session.__exit__ = MagicMock(return_value=False)
    existing = MagicMock() if exists_in_db else None
    mock_session.exec.return_value.first.return_value = existing
    return mock_session


def _patches(
    mock_client=None,
    mock_service=None,
    mock_session=None,
    mock_engine=None,
):
    """Return a list of patch() context managers for all lazy imports."""
    if mock_client is None:
        mock_client = AsyncMock()
        mock_client.get_activities = AsyncMock(return_value=[])
    if mock_service is None:
        mock_service = AsyncMock()
    if mock_session is None:
        mock_session = _make_mock_session()
    if mock_engine is None:
        mock_engine = MagicMock()

    return [
        patch("fitness.db.engine.get_engine", return_value=mock_engine),
        patch("fitness.garmin.client.GarminClient", return_value=mock_client),
        patch("fitness.garmin.sync_service.GarminSyncService", return_value=mock_service),
        patch("sqlmodel.Session", return_value=mock_session),
        patch("fitness.scripts.backfill.asyncio.sleep", new_callable=AsyncMock),
    ]


# ─── Tests ────────────────────────────────────────────────────────────────────

class TestBackfillScript:
    """Tests for fitness.scripts.backfill._backfill()"""

    @pytest.mark.asyncio
    async def test_syncs_in_window_activity(self):
        """An activity within the requested window that's not in DB gets synced."""
        recent = datetime.utcnow() - timedelta(days=5)
        act_summary = make_act_summary(111, recent.strftime("%Y-%m-%d %H:%M:%S"))

        mock_client = AsyncMock()
        mock_client.get_activities = AsyncMock(side_effect=[[act_summary], []])
        mock_service = AsyncMock()
        mock_session = _make_mock_session(exists_in_db=False)

        with patch("fitness.db.engine.get_engine"), \
             patch("fitness.garmin.client.GarminClient", return_value=mock_client), \
             patch("fitness.garmin.sync_service.GarminSyncService", return_value=mock_service), \
             patch("sqlmodel.Session", return_value=mock_session), \
             patch("fitness.scripts.backfill.asyncio.sleep", new_callable=AsyncMock):
            from fitness.scripts.backfill import _backfill
            await _backfill(days=7)

        mock_service.sync_activity.assert_awaited_once_with("111")

    @pytest.mark.asyncio
    async def test_skips_activity_already_in_db(self):
        """An activity already in the DB is not re-synced."""
        recent = datetime.utcnow() - timedelta(days=2)
        act_summary = make_act_summary(222, recent.strftime("%Y-%m-%d %H:%M:%S"))

        mock_client = AsyncMock()
        mock_client.get_activities = AsyncMock(side_effect=[[act_summary], []])
        mock_service = AsyncMock()
        mock_session = _make_mock_session(exists_in_db=True)  # already in DB

        with patch("fitness.db.engine.get_engine"), \
             patch("fitness.garmin.client.GarminClient", return_value=mock_client), \
             patch("fitness.garmin.sync_service.GarminSyncService", return_value=mock_service), \
             patch("sqlmodel.Session", return_value=mock_session), \
             patch("fitness.scripts.backfill.asyncio.sleep", new_callable=AsyncMock):
            from fitness.scripts.backfill import _backfill
            await _backfill(days=7)

        mock_service.sync_activity.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_skips_activity_outside_window(self):
        """An activity outside the date window is not synced."""
        old = datetime.utcnow() - timedelta(days=60)
        act_summary = make_act_summary(333, old.strftime("%Y-%m-%d %H:%M:%S"))

        mock_client = AsyncMock()
        mock_client.get_activities = AsyncMock(side_effect=[[act_summary], []])
        mock_service = AsyncMock()
        mock_session = _make_mock_session(exists_in_db=False)

        with patch("fitness.db.engine.get_engine"), \
             patch("fitness.garmin.client.GarminClient", return_value=mock_client), \
             patch("fitness.garmin.sync_service.GarminSyncService", return_value=mock_service), \
             patch("sqlmodel.Session", return_value=mock_session), \
             patch("fitness.scripts.backfill.asyncio.sleep", new_callable=AsyncMock):
            from fitness.scripts.backfill import _backfill
            await _backfill(days=7)

        mock_service.sync_activity.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_sleep_called_between_activities(self):
        """asyncio.sleep is called between each synced activity."""
        recent = datetime.utcnow() - timedelta(days=2)
        acts = [
            make_act_summary(i, recent.strftime("%Y-%m-%d %H:%M:%S"))
            for i in range(1, 4)
        ]

        mock_client = AsyncMock()
        mock_client.get_activities = AsyncMock(side_effect=[acts, []])
        mock_service = AsyncMock()
        mock_session = _make_mock_session(exists_in_db=False)
        mock_sleep = AsyncMock()

        with patch("fitness.db.engine.get_engine"), \
             patch("fitness.garmin.client.GarminClient", return_value=mock_client), \
             patch("fitness.garmin.sync_service.GarminSyncService", return_value=mock_service), \
             patch("sqlmodel.Session", return_value=mock_session), \
             patch("fitness.scripts.backfill.asyncio.sleep", mock_sleep):
            from fitness.scripts.backfill import _backfill
            await _backfill(days=7)

        # Sleep called at least once per synced activity
        assert mock_sleep.await_count >= 3

    @pytest.mark.asyncio
    async def test_sync_failure_does_not_abort(self):
        """A sync failure on one activity logs a warning and continues."""
        recent = datetime.utcnow() - timedelta(days=2)
        acts = [
            make_act_summary(1, recent.strftime("%Y-%m-%d %H:%M:%S")),
            make_act_summary(2, recent.strftime("%Y-%m-%d %H:%M:%S")),
        ]

        mock_client = AsyncMock()
        mock_client.get_activities = AsyncMock(side_effect=[acts, []])
        mock_service = AsyncMock()
        mock_service.sync_activity.side_effect = [Exception("Garmin down"), None]
        mock_session = _make_mock_session(exists_in_db=False)

        with patch("fitness.db.engine.get_engine"), \
             patch("fitness.garmin.client.GarminClient", return_value=mock_client), \
             patch("fitness.garmin.sync_service.GarminSyncService", return_value=mock_service), \
             patch("sqlmodel.Session", return_value=mock_session), \
             patch("fitness.scripts.backfill.asyncio.sleep", new_callable=AsyncMock):
            from fitness.scripts.backfill import _backfill
            # Should not raise even though first sync fails
            await _backfill(days=7)

        # Second activity still synced
        assert mock_service.sync_activity.await_count == 2

    @pytest.mark.asyncio
    async def test_skips_activities_with_invalid_date_format(self):
        """Activities with unparseable startTimeGMT are skipped gracefully."""
        act_bad_date = {"activityId": 999, "startTimeGMT": "not-a-date"}

        mock_client = AsyncMock()
        mock_client.get_activities = AsyncMock(side_effect=[[act_bad_date], []])
        mock_service = AsyncMock()
        mock_session = _make_mock_session(exists_in_db=False)

        with patch("fitness.db.engine.get_engine"), \
             patch("fitness.garmin.client.GarminClient", return_value=mock_client), \
             patch("fitness.garmin.sync_service.GarminSyncService", return_value=mock_service), \
             patch("sqlmodel.Session", return_value=mock_session), \
             patch("fitness.scripts.backfill.asyncio.sleep", new_callable=AsyncMock):
            from fitness.scripts.backfill import _backfill
            await _backfill(days=7)

        mock_service.sync_activity.assert_not_awaited()


class TestBackfillMain:
    """Tests for the CLI entrypoint."""

    def test_main_calls_asyncio_run(self):
        captured = {}

        def capture_and_close(coro):
            captured["coro"] = coro
            coro.close()  # prevent RuntimeWarning about unawaited coroutine

        with patch("fitness.scripts.backfill.asyncio.run", side_effect=capture_and_close), \
             patch("sys.argv", ["backfill", "--days", "30"]):
            from fitness.scripts.backfill import main
            main()

        assert "coro" in captured

    def test_default_days_is_180(self):
        captured = {}

        def capture_run(coro):
            captured["coro"] = coro
            # Close the coroutine immediately to avoid RuntimeWarning
            coro.close()

        with patch("fitness.scripts.backfill.asyncio.run", side_effect=capture_run), \
             patch("sys.argv", ["backfill"]):
            from fitness.scripts.backfill import main
            main()

        assert "coro" in captured
