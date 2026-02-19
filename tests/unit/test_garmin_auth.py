"""Tests for Garmin session token save/load and GarminAuth."""
import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from fitness.garmin.auth import (
    GarminAuth,
    SessionExpiredError,
    NoSessionError,
    TOKENS_DIR_DEFAULT,
    SESSION_FILE_NAME,
)


# ─── Fixtures ─────────────────────────────────────────────────────────────────

FAKE_SESSION_DATA = {
    "display_name": "testrunner",
    "session_cookies": {"SESSIONID": "abc123", "GARMIN-SSO-GUID": "xyz"},
    "login_cookies": {"CASTGC": "TGT-xyz"},
}


@pytest.fixture
def tmp_tokens_dir(tmp_path):
    """A temporary directory to act as the tokens store."""
    return tmp_path / "garmin_tokens"


@pytest.fixture
def auth(tmp_tokens_dir):
    return GarminAuth(tokens_dir=tmp_tokens_dir)


# ─── Tests: save / load ───────────────────────────────────────────────────────

class TestSaveLoad:
    def test_save_creates_directory(self, auth, tmp_tokens_dir):
        auth.save(FAKE_SESSION_DATA)
        assert tmp_tokens_dir.is_dir()

    def test_save_creates_session_file(self, auth, tmp_tokens_dir):
        auth.save(FAKE_SESSION_DATA)
        assert (tmp_tokens_dir / SESSION_FILE_NAME).exists()

    def test_save_contents_are_valid_json(self, auth, tmp_tokens_dir):
        auth.save(FAKE_SESSION_DATA)
        raw = (tmp_tokens_dir / SESSION_FILE_NAME).read_text()
        parsed = json.loads(raw)
        assert parsed["display_name"] == "testrunner"

    def test_load_returns_session_data(self, auth):
        auth.save(FAKE_SESSION_DATA)
        loaded = auth.load()
        assert loaded["display_name"] == "testrunner"
        assert loaded["session_cookies"] == FAKE_SESSION_DATA["session_cookies"]

    def test_load_raises_no_session_when_missing(self, auth):
        with pytest.raises(NoSessionError):
            auth.load()

    def test_has_session_false_when_missing(self, auth):
        assert auth.has_session() is False

    def test_has_session_true_after_save(self, auth):
        auth.save(FAKE_SESSION_DATA)
        assert auth.has_session() is True

    def test_clear_removes_session_file(self, auth, tmp_tokens_dir):
        auth.save(FAKE_SESSION_DATA)
        auth.clear()
        assert not (tmp_tokens_dir / SESSION_FILE_NAME).exists()

    def test_clear_is_safe_when_no_session(self, auth):
        """clear() should not raise if no session file exists."""
        auth.clear()  # should not raise

    def test_saved_file_permissions_owner_only(self, auth, tmp_tokens_dir):
        """Session file should be readable only by owner (0o600)."""
        auth.save(FAKE_SESSION_DATA)
        session_file = tmp_tokens_dir / SESSION_FILE_NAME
        mode = oct(session_file.stat().st_mode)[-3:]
        assert mode == "600", f"Expected 600, got {mode}"

    def test_saved_dir_permissions_owner_only(self, auth, tmp_tokens_dir):
        """Tokens directory should be accessible only by owner (0o700)."""
        auth.save(FAKE_SESSION_DATA)
        mode = oct(tmp_tokens_dir.stat().st_mode)[-3:]
        assert mode == "700", f"Expected 700, got {mode}"


# ─── Tests: build_client ──────────────────────────────────────────────────────

class TestBuildClient:
    def test_build_client_from_saved_session(self, auth):
        """build_client() should pass session_data to Garmin constructor."""
        auth.save(FAKE_SESSION_DATA)
        with patch("fitness.garmin.auth.garminconnect.Garmin") as MockGarmin:
            instance = MockGarmin.return_value
            instance.login.return_value = True
            client = auth.build_client()
            MockGarmin.assert_called_once_with(session_data=FAKE_SESSION_DATA)

    def test_build_client_raises_no_session_when_missing(self, auth):
        """build_client() without a saved session raises NoSessionError."""
        with pytest.raises(NoSessionError):
            auth.build_client()

    def test_build_client_calls_login(self, auth):
        """build_client() must call login() to validate/restore the session."""
        auth.save(FAKE_SESSION_DATA)
        with patch("fitness.garmin.auth.garminconnect.Garmin") as MockGarmin:
            instance = MockGarmin.return_value
            instance.login.return_value = True
            auth.build_client()
            instance.login.assert_called_once()


# ─── Tests: authenticate_and_save ────────────────────────────────────────────

class TestAuthenticateAndSave:
    def test_saves_session_after_successful_login(self, auth):
        with patch("fitness.garmin.auth.garminconnect.Garmin") as MockGarmin:
            instance = MockGarmin.return_value
            instance.login.return_value = True
            instance.session_data = FAKE_SESSION_DATA

            auth.authenticate_and_save("user@example.com", "password123")

        assert auth.has_session()
        loaded = auth.load()
        assert loaded["display_name"] == "testrunner"

    def test_raises_on_failed_login(self, auth):
        with patch("fitness.garmin.auth.garminconnect.Garmin") as MockGarmin:
            instance = MockGarmin.return_value
            instance.login.side_effect = Exception("401 bad credentials")

            with pytest.raises(Exception, match="401"):
                auth.authenticate_and_save("bad@example.com", "wrongpass")

    def test_does_not_save_on_failed_login(self, auth):
        with patch("fitness.garmin.auth.garminconnect.Garmin") as MockGarmin:
            instance = MockGarmin.return_value
            instance.login.side_effect = Exception("Login failed")
            try:
                auth.authenticate_and_save("bad@example.com", "wrongpass")
            except Exception:
                pass

        assert not auth.has_session()
