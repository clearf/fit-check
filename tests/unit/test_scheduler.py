"""Tests for APScheduler job configuration."""
import pytest
from unittest.mock import MagicMock, patch
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from fitness.scheduler.jobs import build_scheduler


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
