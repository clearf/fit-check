"""
Garmin session-cookie authentication with disk persistence.

garminconnect >= 0.2.x authenticates via Garmin's OAuth2/PKCE flow (via garth)
and stores two token files in a directory:

    ~/.fitness/garmin_session/
        oauth1_token.json
        oauth2_token.json

We save the token directory after first login so the plaintext password is
only needed once. On subsequent starts we restore from the token directory;
if Garmin's servers reject them (expired), garth will attempt a token refresh
automatically. If that also fails, we raise SessionExpiredError and ask the
user to run `python -m fitness setup` again.

Token sessions typically last several weeks to a few months before expiring.
The `python -m fitness setup` wizard must be re-run when they do.
"""
import os
import stat
from pathlib import Path
from typing import Optional

import garminconnect


# ── Constants ─────────────────────────────────────────────────────────────────

TOKENS_DIR_DEFAULT = Path.home() / ".fitness" / "garmin_session"


# ── Exceptions ────────────────────────────────────────────────────────────────

class NoSessionError(RuntimeError):
    """Raised when no saved session exists and credentials were not provided."""


class SessionExpiredError(RuntimeError):
    """Raised when a saved session is rejected by Garmin's servers."""


# ── Main class ────────────────────────────────────────────────────────────────

class GarminAuth:
    """
    Manages Garmin Connect token persistence.

    Usage:
        auth = GarminAuth()
        if not auth.has_session():
            auth.authenticate_and_save(email, password)
        client = auth.build_client()   # → garminconnect.Garmin instance
    """

    def __init__(self, tokens_dir: Path = TOKENS_DIR_DEFAULT):
        self._tokens_dir = Path(tokens_dir)

    # ── Persistence ───────────────────────────────────────────────────────────

    def has_session(self) -> bool:
        """Return True if token files exist on disk."""
        return (self._tokens_dir / "oauth1_token.json").exists()

    def _ensure_dir(self) -> None:
        """Create the tokens directory with owner-only permissions."""
        self._tokens_dir.mkdir(parents=True, exist_ok=True)
        os.chmod(self._tokens_dir, stat.S_IRWXU)  # 0700

    def clear(self) -> None:
        """Delete token files (does not raise if already absent)."""
        for name in ("oauth1_token.json", "oauth2_token.json"):
            f = self._tokens_dir / name
            if f.exists():
                f.unlink()

    # ── Auth ──────────────────────────────────────────────────────────────────

    def authenticate_and_save(self, email: str, password: str) -> garminconnect.Garmin:
        """
        Log in with email + password, save OAuth tokens to disk.

        Args:
            email: Garmin Connect account email.
            password: Garmin Connect account password (not stored on disk).

        Returns:
            Authenticated garminconnect.Garmin instance.

        Raises:
            Any exception from garminconnect/garth on auth failure.
        """
        self._ensure_dir()
        api = garminconnect.Garmin(email=email, password=password)
        api.login()
        api.garth.dump(str(self._tokens_dir))
        # Lock down the token files
        for name in ("oauth1_token.json", "oauth2_token.json"):
            f = self._tokens_dir / name
            if f.exists():
                os.chmod(f, stat.S_IRUSR | stat.S_IWUSR)  # 0600
        return api

    def build_client(self) -> garminconnect.Garmin:
        """
        Build an authenticated Garmin client from the saved tokens.

        Returns:
            Authenticated garminconnect.Garmin instance.

        Raises:
            NoSessionError: if no tokens are saved.
            SessionExpiredError: if the saved tokens are no longer valid.
        """
        if not self.has_session():
            raise NoSessionError(
                f"No Garmin session found at {self._tokens_dir}. "
                "Run `python -m fitness setup` to authenticate."
            )

        api = garminconnect.Garmin()
        try:
            api.login(tokenstore=str(self._tokens_dir))
        except Exception as exc:
            raise SessionExpiredError(
                "Garmin session has expired. "
                "Run `python -m fitness setup` to re-authenticate."
            ) from exc

        return api
