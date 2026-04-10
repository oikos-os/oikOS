"""Tests for Claude Code credential discovery."""

import json
import time
from unittest.mock import patch

from core.auth.claude_discovery import (
    ClaudeCredentials,
    _parse_format_a,
    _parse_format_b,
    discover_claude_credentials,
)


class TestParseFormatA:
    """Format A: nested claudeAiOauth key, camelCase (actual SIGMA-01 format)."""

    def test_parses_valid_format_a(self):
        data = {
            "claudeAiOauth": {
                "accessToken": "sk-ant-oat01-test-token",
                "refreshToken": "sk-ant-ort01-test-refresh",
                "expiresAt": 1773980211741,
                "scopes": ["user:inference", "user:profile"],
                "subscriptionType": "max",
                "rateLimitTier": "default_claude_max_20x",
            }
        }
        creds = _parse_format_a(data, "/fake/path")
        assert creds is not None
        assert creds.access_token == "sk-ant-oat01-test-token"
        assert creds.refresh_token == "sk-ant-ort01-test-refresh"
        assert creds.expires_at == 1773980211741
        assert creds.subscription_type == "max"

    def test_returns_none_on_missing_key(self):
        assert _parse_format_a({"other": {}}, "/fake") is None

    def test_returns_none_on_bad_token_prefix(self):
        data = {
            "claudeAiOauth": {
                "accessToken": "bad-prefix",
                "refreshToken": "sk-ant-ort01-ok",
                "expiresAt": 9999999999999,
            }
        }
        assert _parse_format_a(data, "/fake") is None


class TestParseFormatB:
    """Format B: flat structure, snake_case (brief fallback)."""

    def test_parses_valid_format_b(self):
        data = {
            "access_token": "sk-ant-oat01-test",
            "refresh_token": "sk-ant-ort01-test",
            "expires_in": 28800,
            "scope": "user:inference user:profile",
        }
        creds = _parse_format_b(data, "/fake/path")
        assert creds is not None
        assert creds.access_token == "sk-ant-oat01-test"
        assert creds.expires_at > time.time() * 1000


class TestDiscoverCredentials:
    def test_returns_none_when_no_files_exist(self, tmp_path):
        with patch("core.auth.claude_discovery._get_credential_paths", return_value=[tmp_path / "nonexistent.json"]):
            assert discover_claude_credentials() is None

    def test_finds_format_a_credentials(self, tmp_path):
        cred_file = tmp_path / ".credentials.json"
        cred_file.write_text(json.dumps({
            "claudeAiOauth": {
                "accessToken": "sk-ant-oat01-found",
                "refreshToken": "sk-ant-ort01-found",
                "expiresAt": 9999999999999,
                "scopes": ["user:inference"],
                "subscriptionType": "pro",
            }
        }))
        with patch("core.auth.claude_discovery._get_credential_paths", return_value=[cred_file]):
            creds = discover_claude_credentials()
            assert creds is not None
            assert creds.access_token == "sk-ant-oat01-found"
            assert creds.subscription_type == "pro"
            assert creds.source_path == str(cred_file)

    def test_handles_corrupt_json(self, tmp_path):
        bad_file = tmp_path / "creds.json"
        bad_file.write_text("not valid json{{{")
        with patch("core.auth.claude_discovery._get_credential_paths", return_value=[bad_file]):
            assert discover_claude_credentials() is None

    def test_handles_missing_file(self, tmp_path):
        with patch("core.auth.claude_discovery._get_credential_paths", return_value=[tmp_path / "nope.json"]):
            assert discover_claude_credentials() is None


class TestTokenRefresh:
    def test_refresh_returns_token_on_success(self):
        from unittest.mock import MagicMock

        from core.auth.claude_discovery import RefreshedToken
        from core.auth.refresh import refresh_access_token

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "access_token": "sk-ant-oat01-refreshed",
            "expires_in": 28800,
        }

        with patch("core.auth.refresh.httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.post.return_value = mock_response
            mock_client_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
            mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)

            result = refresh_access_token("sk-ant-ort01-test")
            assert result is not None
            assert isinstance(result, RefreshedToken)
            assert result.access_token == "sk-ant-oat01-refreshed"
            assert result.expires_at > time.time() * 1000

    def test_refresh_returns_none_on_error(self):
        from unittest.mock import MagicMock

        from core.auth.refresh import refresh_access_token

        mock_response = MagicMock()
        mock_response.status_code = 401

        with patch("core.auth.refresh.httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.post.return_value = mock_response
            mock_client_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
            mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)

            result = refresh_access_token("sk-ant-ort01-bad")
            assert result is None
