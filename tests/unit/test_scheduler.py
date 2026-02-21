"""Tests for APScheduler job configuration and nightly sync job body."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from fitness.scheduler.jobs import build_scheduler, _nightly_sync


class TestBuildScheduler:
    def test_returns_scheduler(self):
        engine = MagicMock()
        scheduler = build_scheduler(engine)
        assert isinstance(scheduler, AsyncIOScheduler)

    def test_nightly_sync_job_registered(self):
        engine = MagicMock()
        scheduler = build_scheduler(engine)
        job_ids = [job.id for job in scheduler.get_jobs()]
        assert "nightly_sync" in job_ids

    def test_nightly_sync_is_cron(self):
        engine = MagicMock()
        scheduler = build_scheduler(engine)
        job = next(j for j in scheduler.get_jobs() if j.id == "nightly_sync")
        assert job.trigger.__class__.__name__ == "CronTrigger"

    def test_sync_hour_from_settings(self):
        """Scheduler respects the GARMIN_SYNC_HOUR setting."""
        engine = MagicMock()
        with patch("fitness.scheduler.jobs.get_settings") as mock_settings:
            mock_settings.return_value.garmin_sync_hour = 4
            scheduler = build_scheduler(engine)

        job = next(j for j in scheduler.get_jobs() if j.id == "nightly_sync")
        # CronTrigger field 'hour' should equal 4
        fields = {f.name: f for f in job.trigger.fields}
        assert str(fields["hour"]) == "4"

    def test_scheduler_not_running_on_creation(self):
        """build_scheduler should not auto-start."""
        engine = MagicMock()
        scheduler = build_scheduler(engine)
        assert not scheduler.running


# ─── _nightly_sync job body ────────────────────────────────────────────────────

class TestNightlySyncJob:
    """Tests for the _nightly_sync() async function.

    GarminClient and GarminSyncService are lazily imported inside the function
    body, so we patch them at their source module paths rather than on the
    scheduler.jobs namespace.
    """

    @pytest.mark.asyncio
    async def test_connects_garmin_client(self):
        mock_engine = MagicMock()
        mock_client = AsyncMock()
        mock_client.get_activities = AsyncMock(return_value=[])
        mock_service = AsyncMock()

        with patch("fitness.garmin.client.GarminClient", return_value=mock_client), \
             patch("fitness.garmin.sync_service.GarminSyncService", return_value=mock_service), \
             patch("fitness.scheduler.jobs.get_settings") as mock_settings:
            mock_settings.return_value.garmin_sync_hour = 3
            await _nightly_sync(engine=mock_engine)

        mock_client.connect.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_syncs_recent_activities(self):
        mock_engine = MagicMock()
        mock_client = AsyncMock()
        mock_client.get_activities = AsyncMock(return_value=[
            {"activityId": 101},
            {"activityId": 102},
        ])
        mock_service = AsyncMock()

        with patch("fitness.garmin.client.GarminClient", return_value=mock_client), \
             patch("fitness.garmin.sync_service.GarminSyncService", return_value=mock_service), \
             patch("fitness.scheduler.jobs.get_settings") as mock_settings:
            mock_settings.return_value.garmin_sync_hour = 3
            await _nightly_sync(engine=mock_engine)

        assert mock_service.sync_activity.await_count == 2
        mock_service.sync_activity.assert_any_await("101")
        mock_service.sync_activity.assert_any_await("102")

    @pytest.mark.asyncio
    async def test_fetches_three_most_recent_activities(self):
        """Nightly sync should request limit=3 to catch late-syncing activities."""
        mock_engine = MagicMock()
        mock_client = AsyncMock()
        mock_client.get_activities = AsyncMock(return_value=[])
        mock_service = AsyncMock()

        with patch("fitness.garmin.client.GarminClient", return_value=mock_client), \
             patch("fitness.garmin.sync_service.GarminSyncService", return_value=mock_service), \
             patch("fitness.scheduler.jobs.get_settings") as mock_settings:
            mock_settings.return_value.garmin_sync_hour = 3
            await _nightly_sync(engine=mock_engine)

        mock_client.get_activities.assert_awaited_once_with(start=0, limit=3)

    @pytest.mark.asyncio
    async def test_exception_does_not_propagate(self):
        """Nightly sync catches all exceptions so the scheduler stays alive."""
        mock_engine = MagicMock()
        mock_client = AsyncMock()
        mock_client.connect.side_effect = Exception("Connection refused")

        with patch("fitness.garmin.client.GarminClient", return_value=mock_client), \
             patch("fitness.scheduler.jobs.get_settings") as mock_settings:
            mock_settings.return_value.garmin_sync_hour = 3
            # Should not raise
            await _nightly_sync(engine=mock_engine)

    @pytest.mark.asyncio
    async def test_skips_activities_with_no_id(self):
        """Activities without activityId key are skipped gracefully.

        Note: activityId=0 is treated as string "0" which is truthy, so
        only truly missing keys (empty activityId via .get()) are skipped.
        """
        mock_engine = MagicMock()
        mock_client = AsyncMock()
        mock_client.get_activities = AsyncMock(return_value=[
            {},           # no activityId key → str("") → falsy → skipped
            {"name": "Run"},  # also missing activityId key → skipped
        ])
        mock_service = AsyncMock()

        with patch("fitness.garmin.client.GarminClient", return_value=mock_client), \
             patch("fitness.garmin.sync_service.GarminSyncService", return_value=mock_service), \
             patch("fitness.scheduler.jobs.get_settings") as mock_settings:
            mock_settings.return_value.garmin_sync_hour = 3
            await _nightly_sync(engine=mock_engine)

        mock_service.sync_activity.assert_not_awaited()
