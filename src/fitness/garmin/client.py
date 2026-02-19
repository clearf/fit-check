"""
Async wrapper around the garminconnect library.

garminconnect is synchronous; we run it in a thread pool executor so it
doesn't block the asyncio event loop.
"""
import asyncio
import tempfile
from datetime import date
from pathlib import Path
from typing import Any, Dict, List

import garminconnect

from fitness.garmin.fit_parser import parse_fit_file


class GarminClient:
    """Thin async wrapper over garminconnect.Garmin."""

    def __init__(self, email: str, password: str):
        self._email = email
        self._password = password
        self._api: garminconnect.Garmin = None

    async def connect(self) -> None:
        """Authenticate with Garmin Connect."""
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self._connect_sync)

    def _connect_sync(self) -> None:
        self._api = garminconnect.Garmin(self._email, self._password)
        self._api.login()

    async def _run(self, fn, *args, **kwargs):
        """Run a sync garminconnect call in the thread pool."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, lambda: fn(*args, **kwargs))

    async def get_activity_summary(self, activity_id: str) -> Dict[str, Any]:
        """Fetch activity summary dict from Garmin Connect API."""
        return await self._run(self._api.get_activity, activity_id)

    async def get_activity_typed_splits(self, activity_id: str) -> List[Dict]:
        """Fetch typed splits (run/walk segments) for a Galloway run."""
        result = await self._run(
            self._api.get_activity_typed_splits, activity_id
        )
        # API returns {"activityId": ..., "typeIDs": [...]} or list directly
        if isinstance(result, list):
            return result
        return result.get("typeIDs", [])

    async def get_sleep_data(self, date_str: str) -> Dict[str, Any]:
        """Fetch sleep data for a given date string 'YYYY-MM-DD'."""
        return await self._run(self._api.get_sleep_data, date_str)

    async def get_hrv_data(self, date_str: str) -> Dict[str, Any]:
        """Fetch HRV data for a given date string 'YYYY-MM-DD'."""
        return await self._run(self._api.get_hrv_data, date_str)

    async def get_activities(
        self,
        start: int = 0,
        limit: int = 20,
        activity_type: str = "running",
    ) -> List[Dict[str, Any]]:
        """Fetch a page of activities."""
        return await self._run(
            self._api.get_activities, start, limit, activitytype=activity_type
        )

    async def get_fit_datapoints(self, activity_id: str) -> List[Dict[str, Any]]:
        """
        Download the FIT file for an activity and parse it into datapoint dicts.

        Downloads to a temp file, parses with fitparse, then deletes the temp file.
        """
        # Download FIT binary
        fit_data = await self._run(self._api.download_activity, activity_id)

        # Write to temp file and parse
        with tempfile.NamedTemporaryFile(suffix=".fit", delete=False) as f:
            tmp_path = Path(f.name)
            f.write(fit_data)

        try:
            datapoints = parse_fit_file(tmp_path)
        finally:
            tmp_path.unlink(missing_ok=True)

        return datapoints
