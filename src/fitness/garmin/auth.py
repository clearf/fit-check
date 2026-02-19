"""
Garmin session-cookie authentication with disk persistence.

garminconnect==0.1.55 authenticates via Garmin's SSO login flow and
produces a `session_data` dict containing the resulting cookies:

    {
        "display_name": "yourname",
        "session_cookies": { ... },  # connect.garmin.com session cookies
        "login_cookies":  { ... },   # sso.garmin.com login cookies
    }

We serialize this to JSON on disk so the plaintext password is only
needed once. On subsequent starts we restore the cookies; if Garmin's
servers reject them (expired), the library automatically re-authenticates
using the stored credentials — but since we DON'T store the password, we
raise SessionExpiredError and ask the user to run `python -m fitness setup`
again.

Cookie sessions typically last several weeks to a few months before
expiring.  The `python -m fitness setup` wizard must be re-run when
they do.
"""
import json
import os
import stat
from pathlib import Path
from typing import Any, Dict

import garminconnect

# ── Constants ─────────────────────────────────────────────────────────────────

TOKENS_DIR_DEFAULT = Path.home() / ".fitness" / "garmin_session"
SESSION_FILE_NAME = "session.json"


# ── Exceptions ────────────────────────────────────────────────────────────────

class NoSessionError(RuntimeError):
    """Raised when no saved session exists and credentials were not provided."""


class SessionExpiredError(RuntimeError):
    """Raised when a saved session is rejected by Garmin's servers."""


# ── Main class ────────────────────────────────────────────────────────────────

class GarminAuth:
    """
    Manages Garmin Connect session persistence.

    Usage:
        auth = GarminAuth()
        if not auth.has_session():
            auth.authenticate_and_save(email, password)
        client = auth.build_client()   # → garminconnect.Garmin instance
    """

    def __init__(self, tokens_dir: Path = TOKENS_DIR_DEFAULT):
        self._tokens_dir = Path(tokens_dir)
        self._session_file = self._tokens_dir / SESSION_FILE_NAME

    # ── Persistence ───────────────────────────────────────────────────────────

    def has_session(self) -> bool:
        """Return True if a session file exists on disk."""
        return self._session_file.exists()

    def save(self, session_data: Dict[str, Any]) -> None:
        """
        Persist session_data to disk with owner-only permissions.

        Directory: 0700 (rwx------)
        File:      0600 (rw-------)
        """
        self._tokens_dir.mkdir(parents=True, exist_ok=True)
        os.chmod(self._tokens_dir, stat.S_IRWXU)  # 0700

        self._session_file.write_text(json.dumps(session_data, indent=2))
        os.chmod(self._session_file, stat.S_IRUSR | stat.S_IWUSR)  # 0600

    def load(self) -> Dict[str, Any]:
        """
        Load session_data from disk.

        Raises:
            NoSessionError: if no session file exists.
        """
        if not self._session_file.exists():
            raise NoSessionError(
                f"No Garmin session found at {self._session_file}. "
                "Run `python -m fitness setup` to authenticate."
            )
        return json.loads(self._session_file.read_text())

    def clear(self) -> None:
        """Delete the session file (does not raise if already absent)."""
        if self._session_file.exists():
            self._session_file.unlink()

    # ── Auth ──────────────────────────────────────────────────────────────────

    def authenticate_and_save(self, email: str, password: str) -> garminconnect.Garmin:
        """
        Log in with email + password, save session cookies to disk.

        Args:
            email: Garmin Connect account email.
            password: Garmin Connect account password (not stored on disk).

        Returns:
            Authenticated garminconnect.Garmin instance.

        Raises:
            Any exception from garminconnect on auth failure.
        """
        api = garminconnect.Garmin(email, password)
        api.login()  # raises on bad credentials

        self.save(api.session_data)
        return api

    def build_client(self) -> garminconnect.Garmin:
        """
        Build an authenticated Garmin client from the saved session.

        Calls login() to validate/restore cookies. If the session has
        expired and the library cannot silently re-authenticate (because
        we don't store the password), raises SessionExpiredError.

        Returns:
            Authenticated garminconnect.Garmin instance.

        Raises:
            NoSessionError: if no session is saved.
            SessionExpiredError: if the saved session is no longer valid.
        """
        session_data = self.load()  # raises NoSessionError if missing

        api = garminconnect.Garmin(session_data=session_data)
        try:
            api.login()
        except Exception as exc:
            # login() tried to re-authenticate with empty credentials and failed
            raise SessionExpiredError(
                "Garmin session has expired. "
                "Run `python -m fitness setup` to re-authenticate."
            ) from exc

        return api
