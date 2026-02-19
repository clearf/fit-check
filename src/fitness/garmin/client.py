"""
Async wrapper around the garminconnect library.

garminconnect is synchronous; we run it in a thread pool executor so it
doesn't block the asyncio event loop.

Authentication is handled via GarminAuth (session cookies on disk).
Credentials are never stored in config or env — only the session cookies.
"""
import asyncio
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

import garminconnect

from fitness.garmin.auth import GarminAuth, NoSessionError, SessionExpiredError
from fitness.garmin.fit_parser import parse_fit_file


class GarminClient:
    """
    Thin async wrapper over garminconnect.Garmin.

    Call connect() before any data methods. connect() loads the saved session
    from disk via GarminAuth — no credentials are required at runtime.
    """

    def __init__(self, auth: Optional[GarminAuth] = None):
        """
        Args:
            auth: GarminAuth instance. Defaults to GarminAuth() which reads
                  from ~/.fitness/garmin_session/.
        """
        self._auth = auth or GarminAuth()
        self._api: Optional[garminconnect.Garmin] = None

    async def connect(self) -> None:
        """
        Load saved session from disk and validate it with Garmin's servers.

        Raises:
            NoSessionError: if `python -m fitness setup` has not been run.
            SessionExpiredError: if the session has expired (re-run setup).
        """
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self._connect_sync)

    def _connect_sync(self) -> None:
        self._api = self._auth.build_client()

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
        fit_data = await self._run(self._api.download_activity, activity_id)

        with tempfile.NamedTemporaryFile(suffix=".fit", delete=False) as f:
            tmp_path = Path(f.name)
            f.write(fit_data)

        try:
            datapoints = parse_fit_file(tmp_path)
        finally:
            tmp_path.unlink(missing_ok=True)

        return datapoints
