"""Tests for GarminAuth OAuth2/garth token persistence."""
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from fitness.garmin.auth import (
    GarminAuth,
    NoSessionError,
    SessionExpiredError,
    TOKENS_DIR_DEFAULT,
)


# ─── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def tmp_tokens_dir(tmp_path):
    """A temporary directory to act as the token store."""
    return tmp_path / "garmin_tokens"


@pytest.fixture
def auth(tmp_tokens_dir):
    return GarminAuth(tokens_dir=tmp_tokens_dir)


@pytest.fixture
def auth_with_tokens(auth, tmp_tokens_dir):
    """GarminAuth with fake token files already present."""
    tmp_tokens_dir.mkdir(parents=True)
    (tmp_tokens_dir / "oauth1_token.json").write_text('{"oauth_token": "tok1"}')
    (tmp_tokens_dir / "oauth2_token.json").write_text('{"access_token": "tok2"}')
    return auth


# ─── Tests: has_session ───────────────────────────────────────────────────────

class TestHasSession:
    def test_false_when_no_directory(self, auth):
        assert auth.has_session() is False

    def test_false_when_directory_exists_but_no_token(self, auth, tmp_tokens_dir):
        tmp_tokens_dir.mkdir(parents=True)
        assert auth.has_session() is False

    def test_false_when_only_oauth2_token_exists(self, auth, tmp_tokens_dir):
        tmp_tokens_dir.mkdir(parents=True)
        (tmp_tokens_dir / "oauth2_token.json").write_text("{}")
        assert auth.has_session() is False

    def test_true_when_oauth1_token_exists(self, auth, tmp_tokens_dir):
        tmp_tokens_dir.mkdir(parents=True)
        (tmp_tokens_dir / "oauth1_token.json").write_text("{}")
        assert auth.has_session() is True

    def test_true_when_both_tokens_exist(self, auth_with_tokens):
        assert auth_with_tokens.has_session() is True


# ─── Tests: clear ─────────────────────────────────────────────────────────────

class TestClear:
    def test_clear_removes_oauth1_token(self, auth_with_tokens, tmp_tokens_dir):
        auth_with_tokens.clear()
        assert not (tmp_tokens_dir / "oauth1_token.json").exists()

    def test_clear_removes_oauth2_token(self, auth_with_tokens, tmp_tokens_dir):
        auth_with_tokens.clear()
        assert not (tmp_tokens_dir / "oauth2_token.json").exists()

    def test_clear_is_safe_when_no_tokens(self, auth):
        """clear() should not raise if token files do not exist."""
        auth.clear()  # should not raise

    def test_clear_is_safe_when_only_one_token(self, auth, tmp_tokens_dir):
        tmp_tokens_dir.mkdir(parents=True)
        (tmp_tokens_dir / "oauth1_token.json").write_text("{}")
        auth.clear()  # should not raise even with oauth2 absent
        assert not (tmp_tokens_dir / "oauth1_token.json").exists()

    def test_has_session_false_after_clear(self, auth_with_tokens):
        auth_with_tokens.clear()
        assert auth_with_tokens.has_session() is False


# ─── Tests: authenticate_and_save ────────────────────────────────────────────

class TestAuthenticateAndSave:
    def _make_mock_instance(self, tmp_tokens_dir=None):
        """Return a mock garminconnect.Garmin instance.

        If tmp_tokens_dir is given, garth.dump() will write real token files
        so that has_session() returns True after the call.
        """
        instance = MagicMock()
        instance.login.return_value = None

        if tmp_tokens_dir is not None:
            def fake_dump(path):
                p = Path(path)
                (p / "oauth1_token.json").write_text('{"oauth_token": "t1"}')
                (p / "oauth2_token.json").write_text('{"access_token": "t2"}')
            instance.garth.dump.side_effect = fake_dump
        else:
            instance.garth.dump.return_value = None

        return instance

    def test_creates_token_directory(self, auth, tmp_tokens_dir):
        with patch("fitness.garmin.auth.garminconnect.Garmin") as MockGarmin:
            MockGarmin.return_value = self._make_mock_instance(tmp_tokens_dir)
            auth.authenticate_and_save("user@example.com", "s3cr3t")

        assert tmp_tokens_dir.is_dir()

    def test_token_dir_gets_0700_permissions(self, auth, tmp_tokens_dir):
        with patch("fitness.garmin.auth.garminconnect.Garmin") as MockGarmin:
            MockGarmin.return_value = self._make_mock_instance()
            auth.authenticate_and_save("user@example.com", "s3cr3t")

        mode = oct(tmp_tokens_dir.stat().st_mode)[-3:]
        assert mode == "700", f"Expected 700, got {mode}"

    def test_constructs_garmin_with_credentials(self, auth):
        with patch("fitness.garmin.auth.garminconnect.Garmin") as MockGarmin:
            MockGarmin.return_value = self._make_mock_instance()
            auth.authenticate_and_save("user@example.com", "s3cr3t")

        MockGarmin.assert_called_once_with(email="user@example.com", password="s3cr3t")

    def test_calls_login(self, auth):
        with patch("fitness.garmin.auth.garminconnect.Garmin") as MockGarmin:
            instance = self._make_mock_instance()
            MockGarmin.return_value = instance
            auth.authenticate_and_save("user@example.com", "s3cr3t")

        instance.login.assert_called_once()

    def test_calls_garth_dump_with_token_dir(self, auth, tmp_tokens_dir):
        with patch("fitness.garmin.auth.garminconnect.Garmin") as MockGarmin:
            instance = self._make_mock_instance()
            MockGarmin.return_value = instance
            auth.authenticate_and_save("user@example.com", "s3cr3t")

        instance.garth.dump.assert_called_once_with(str(tmp_tokens_dir))

    def test_token_files_get_0600_permissions(self, auth, tmp_tokens_dir):
        with patch("fitness.garmin.auth.garminconnect.Garmin") as MockGarmin:
            MockGarmin.return_value = self._make_mock_instance(tmp_tokens_dir)
            auth.authenticate_and_save("user@example.com", "s3cr3t")

        for name in ("oauth1_token.json", "oauth2_token.json"):
            f = tmp_tokens_dir / name
            mode = oct(f.stat().st_mode)[-3:]
            assert mode == "600", f"{name}: expected 600, got {mode}"

    def test_has_session_true_after_successful_save(self, auth, tmp_tokens_dir):
        with patch("fitness.garmin.auth.garminconnect.Garmin") as MockGarmin:
            MockGarmin.return_value = self._make_mock_instance(tmp_tokens_dir)
            auth.authenticate_and_save("user@example.com", "s3cr3t")

        assert auth.has_session() is True

    def test_returns_authenticated_api_instance(self, auth):
        with patch("fitness.garmin.auth.garminconnect.Garmin") as MockGarmin:
            instance = self._make_mock_instance()
            MockGarmin.return_value = instance
            result = auth.authenticate_and_save("user@example.com", "s3cr3t")

        assert result is instance

    def test_raises_on_login_failure(self, auth):
        with patch("fitness.garmin.auth.garminconnect.Garmin") as MockGarmin:
            instance = self._make_mock_instance()
            MockGarmin.return_value = instance
            instance.login.side_effect = Exception("401 bad credentials")

            with pytest.raises(Exception, match="401"):
                auth.authenticate_and_save("bad@example.com", "wrongpass")

    def test_does_not_save_tokens_on_login_failure(self, auth):
        with patch("fitness.garmin.auth.garminconnect.Garmin") as MockGarmin:
            instance = self._make_mock_instance()
            MockGarmin.return_value = instance
            instance.login.side_effect = Exception("Login failed")

            try:
                auth.authenticate_and_save("bad@example.com", "wrongpass")
            except Exception:
                pass

        assert not auth.has_session()


# ─── Tests: build_client ──────────────────────────────────────────────────────

class TestBuildClient:
    def test_raises_no_session_when_no_tokens(self, auth):
        with pytest.raises(NoSessionError):
            auth.build_client()

    def test_constructs_garmin_with_no_credentials(self, auth_with_tokens):
        with patch("fitness.garmin.auth.garminconnect.Garmin") as MockGarmin:
            instance = MagicMock()
            instance.login.return_value = None
            MockGarmin.return_value = instance

            auth_with_tokens.build_client()

        MockGarmin.assert_called_once_with()

    def test_calls_login_with_tokenstore(self, auth_with_tokens, tmp_tokens_dir):
        with patch("fitness.garmin.auth.garminconnect.Garmin") as MockGarmin:
            instance = MagicMock()
            instance.login.return_value = None
            MockGarmin.return_value = instance

            auth_with_tokens.build_client()

        instance.login.assert_called_once_with(tokenstore=str(tmp_tokens_dir))

    def test_returns_authenticated_client(self, auth_with_tokens):
        with patch("fitness.garmin.auth.garminconnect.Garmin") as MockGarmin:
            instance = MagicMock()
            instance.login.return_value = None
            MockGarmin.return_value = instance

            result = auth_with_tokens.build_client()

        assert result is instance

    def test_raises_session_expired_when_login_fails(self, auth_with_tokens):
        with patch("fitness.garmin.auth.garminconnect.Garmin") as MockGarmin:
            instance = MagicMock()
            instance.login.side_effect = Exception("Token expired")
            MockGarmin.return_value = instance

            with pytest.raises(SessionExpiredError):
                auth_with_tokens.build_client()

    def test_session_expired_error_chains_original(self, auth_with_tokens):
        """SessionExpiredError should chain the original exception via __cause__."""
        original = Exception("Token expired")
        with patch("fitness.garmin.auth.garminconnect.Garmin") as MockGarmin:
            instance = MagicMock()
            instance.login.side_effect = original
            MockGarmin.return_value = instance

            with pytest.raises(SessionExpiredError) as exc_info:
                auth_with_tokens.build_client()

        assert exc_info.value.__cause__ is original


# ─── Tests: defaults ──────────────────────────────────────────────────────────

class TestDefaults:
    def test_default_tokens_dir_is_under_home(self):
        expected = Path.home() / ".fitness" / "garmin_session"
        assert TOKENS_DIR_DEFAULT == expected

    def test_default_auth_uses_default_dir(self):
        auth = GarminAuth()
        assert auth._tokens_dir == TOKENS_DIR_DEFAULT

    def test_custom_tokens_dir_is_respected(self, tmp_tokens_dir):
        auth = GarminAuth(tokens_dir=tmp_tokens_dir)
        assert auth._tokens_dir == tmp_tokens_dir
