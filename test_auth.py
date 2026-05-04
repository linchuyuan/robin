import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import auth


class TestAuthSessionHandling(unittest.TestCase):
    def test_null_cache_is_discarded_and_login_is_cached(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache_path = Path(tmp) / "session.json"
            cache_path.write_text("null")
            session = {"access_token": "token-123", "token_type": "Bearer", "refresh_token": "refresh-123", "expires_in": 86400}

            with (
                patch.object(auth, "SESSION_CACHE", cache_path),
                patch.object(auth, "_now", return_value=1000.0),
                patch.object(auth, "get_credentials", return_value=("user", "pass", None)),
                patch.object(auth.rh, "login", return_value=session) as mock_login,
                patch.object(auth.rh, "update_session") as mock_update_session,
            ):
                result = auth.get_session()
                cached_session = json.loads(cache_path.read_text())

        self.assertEqual(result["access_token"], session["access_token"])
        self.assertEqual(result["refresh_token"], session["refresh_token"])
        self.assertEqual(result["created_at"], 1000.0)
        self.assertEqual(result["expires_at"], 87400.0)
        mock_login.assert_called_once_with("user", "pass", mfa_code=None)
        mock_update_session.assert_called_once_with("Authorization", "Bearer token-123")
        self.assertEqual(cached_session["access_token"], session["access_token"])

    def test_cached_session_refreshes_before_expiry(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache_path = Path(tmp) / "session.json"
            cache_path.write_text(json.dumps({
                "access_token": "old-token",
                "refresh_token": "refresh-123",
                "token_type": "Bearer",
                "created_at": 1000.0,
                "expires_in": 86400,
                "expires_at": 2000.0,
            }))
            refreshed = {
                "access_token": "new-token",
                "refresh_token": "new-refresh",
                "token_type": "Bearer",
                "expires_in": 86400,
            }

            with (
                patch.object(auth, "SESSION_CACHE", cache_path),
                patch.object(auth, "_now", return_value=1500.0),
                patch.object(auth.rh_auth, "request_post", return_value=refreshed) as mock_refresh,
                patch.object(auth.rh, "update_session") as mock_update_session,
            ):
                result = auth.get_session()
                cached_session = json.loads(cache_path.read_text())

        self.assertEqual(result["access_token"], "new-token")
        self.assertEqual(cached_session["expires_at"], 87900.0)
        mock_refresh.assert_called_once()
        payload = mock_refresh.call_args.args[1]
        self.assertEqual(payload["grant_type"], "refresh_token")
        self.assertEqual(payload["refresh_token"], "refresh-123")
        mock_update_session.assert_called_once_with("Authorization", "Bearer new-token")

    def test_mcp_mode_requires_manual_login_when_refresh_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache_path = Path(tmp) / "session.json"
            cache_path.write_text(json.dumps({
                "access_token": "old-token",
                "refresh_token": "refresh-123",
                "token_type": "Bearer",
                "created_at": 1000.0,
                "expires_in": 86400,
                "expires_at": 2000.0,
            }))

            with (
                patch.dict(os.environ, {"MCP_SERVER_MODE": "1"}, clear=True),
                patch.object(auth, "SESSION_CACHE", cache_path),
                patch.object(auth, "_now", return_value=1500.0),
                patch.object(auth.rh_auth, "request_post", return_value={"error": "invalid_grant"}),
            ):
                with self.assertRaises(auth.AuthenticationError) as exc:
                    auth.get_session()

        self.assertIn("manual login", exc.exception.message.lower())

    def test_failed_login_response_is_not_cached(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache_path = Path(tmp) / "session.json"

            with (
                patch.object(auth, "SESSION_CACHE", cache_path),
                patch.object(auth, "get_credentials", return_value=("user", "pass", None)),
                patch.object(auth.rh, "login", return_value=None),
            ):
                with self.assertRaises(auth.AuthenticationError) as exc:
                    auth.get_session()

        self.assertIn("no access token", exc.exception.message)
        self.assertFalse(cache_path.exists())

    def test_mcp_mode_requires_non_interactive_credentials(self):
        with patch.dict(os.environ, {"MCP_SERVER_MODE": "1"}, clear=True):
            with self.assertRaises(auth.AuthenticationError) as exc:
                auth.get_credentials()

        self.assertIn("Authentication required", exc.exception.message)


if __name__ == "__main__":
    unittest.main()
