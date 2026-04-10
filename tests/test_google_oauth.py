"""Tests for Google OAuth flow."""

import time
from unittest.mock import MagicMock, patch

from core.auth.google_oauth import (
    GoogleTokens,
    disconnect_google,
    exchange_code,
    get_authorization_url,
    get_google_tokens,
    is_google_connected,
    verify_state,
)


class TestAuthorizationUrl:
    @patch.dict("os.environ", {"GOOGLE_CLIENT_ID": "test-client-id", "GOOGLE_CLIENT_SECRET": "test-secret"})
    def test_generates_url_with_scopes(self):
        url, state = get_authorization_url()
        assert "accounts.google.com" in url
        assert "test-client-id" in url
        assert "gmail" in url
        assert "calendar" in url
        assert state is not None
        assert len(state) > 10

    @patch.dict("os.environ", {"GOOGLE_CLIENT_ID": "test-client-id"})
    def test_state_verifies(self):
        _, state = get_authorization_url()
        assert verify_state(state) is True
        assert verify_state("wrong-state") is False

    @patch.dict("os.environ", {"GOOGLE_CLIENT_ID": "", "GOOGLE_CLIENT_SECRET": ""})
    def test_raises_without_client_id(self):
        import pytest

        with pytest.raises(ValueError, match="GOOGLE_CLIENT_ID"):
            get_authorization_url()


class TestCodeExchange:
    @patch.dict("os.environ", {"GOOGLE_CLIENT_ID": "test-id", "GOOGLE_CLIENT_SECRET": "test-secret"})
    def test_exchange_returns_tokens_on_success(self):
        mock_token_resp = MagicMock()
        mock_token_resp.status_code = 200
        mock_token_resp.json.return_value = {
            "access_token": "ya29.test-token",
            "refresh_token": "1//test-refresh",
            "expires_in": 3600,
            "scope": "openid email profile",
        }

        mock_info_resp = MagicMock()
        mock_info_resp.status_code = 200
        mock_info_resp.json.return_value = {"email": "user@gmail.com"}

        with patch("core.auth.google_oauth.httpx.Client") as mock_cls:
            mock_client = MagicMock()
            mock_client.post.return_value = mock_token_resp
            mock_client.get.return_value = mock_info_resp
            mock_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
            mock_cls.return_value.__exit__ = MagicMock(return_value=False)

            result = exchange_code("test-auth-code")
            assert result is not None
            assert isinstance(result, GoogleTokens)
            assert result.email == "user@gmail.com"
            assert result.access_token == "ya29.test-token"
            assert result.expires_at > time.time() * 1000

    @patch.dict("os.environ", {"GOOGLE_CLIENT_ID": "test-id", "GOOGLE_CLIENT_SECRET": "test-secret"})
    def test_exchange_returns_none_on_error(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 400

        with patch("core.auth.google_oauth.httpx.Client") as mock_cls:
            mock_client = MagicMock()
            mock_client.post.return_value = mock_resp
            mock_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
            mock_cls.return_value.__exit__ = MagicMock(return_value=False)

            result = exchange_code("bad-code")
            assert result is None


class TestTokenManagement:
    def test_disconnect_clears_tokens(self):
        import core.auth.google_oauth as mod

        mod._google_tokens = GoogleTokens(
            access_token="test", refresh_token="test",
            expires_at=9999999999999, email="test@test.com", scopes=[],
        )
        assert is_google_connected() is True
        disconnect_google()
        assert is_google_connected() is False
        assert get_google_tokens() is None

    def test_get_tokens_returns_none_when_disconnected(self):
        import core.auth.google_oauth as mod

        mod._google_tokens = None
        assert get_google_tokens() is None

    def test_repr_redacts_token(self):
        t = GoogleTokens(
            access_token="ya29.secret",
            refresh_token="1//secret",
            expires_at=9999999999999,
            email="test@test.com",
            scopes=[],
        )
        assert "ya29.secret" not in repr(t)
        assert "REDACTED" in repr(t)
