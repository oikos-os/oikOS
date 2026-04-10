"""Tests for OAuth API endpoints."""

from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient


def _make_test_client():
    from core.interface.api.server import create_app

    app = create_app(dev=True)
    return TestClient(app)


def _make_creds(**overrides):
    from core.auth.claude_discovery import ClaudeCredentials

    defaults = {
        "access_token": "sk-ant-oat01-test",
        "refresh_token": "sk-ant-ort01-test",
        "expires_at": 9999999999999,
        "scopes": ["user:inference"],
        "subscription_type": "max",
        "source_path": "/fake/path",
    }
    defaults.update(overrides)
    return ClaudeCredentials(**defaults)


class TestClaudeDiscover:
    @patch("core.auth.claude_discovery.discover_claude_credentials")
    def test_discover_returns_found(self, mock_discover):
        mock_discover.return_value = _make_creds()
        client = _make_test_client()
        resp = client.get("/api/auth/claude/discover")
        assert resp.status_code == 200
        data = resp.json()
        assert data["found"] is True
        assert data["subscription_type"] == "max"
        assert "source_path" not in data

    @patch("core.auth.claude_discovery.discover_claude_credentials")
    def test_discover_returns_not_found(self, mock_discover):
        mock_discover.return_value = None
        client = _make_test_client()
        resp = client.get("/api/auth/claude/discover")
        assert resp.status_code == 200
        assert resp.json()["found"] is False


class TestClaudeConnect:
    @patch("core.cognition.pipeline.dispatch.get_provider_registry")
    @patch("core.auth.claude_discovery.discover_claude_credentials")
    def test_connect_activates_provider(self, mock_discover, mock_reg):
        mock_discover.return_value = _make_creds()
        registry = MagicMock()
        mock_reg.return_value = registry

        client = _make_test_client()
        resp = client.post("/api/auth/claude/connect")
        assert resp.status_code == 200
        assert resp.json()["connected"] is True
        registry.register.assert_called_once()
        registry.set_default.assert_called_once_with("anthropic-oauth")

    @patch("core.auth.claude_discovery.discover_claude_credentials")
    def test_connect_returns_404_no_creds(self, mock_discover):
        mock_discover.return_value = None
        client = _make_test_client()
        resp = client.post("/api/auth/claude/connect")
        assert resp.status_code == 404


class TestClaudeStatus:
    @patch("core.auth.claude_discovery.discover_claude_credentials")
    @patch("core.cognition.pipeline.dispatch.get_provider_registry")
    def test_status_when_connected(self, mock_reg, mock_discover):
        registry = MagicMock()
        registry.get_default_name.return_value = "anthropic-oauth"
        provider = MagicMock()
        provider.is_available.return_value = True
        provider._credentials = MagicMock()
        provider._credentials.subscription_type = "max"
        provider._credentials.expires_at = 9999999999999
        registry.get.return_value = provider
        registry.list_all.return_value = ["local", "anthropic-oauth"]
        mock_reg.return_value = registry
        mock_discover.return_value = MagicMock()

        client = _make_test_client()
        resp = client.get("/api/auth/claude/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["connected"] is True
        assert data["credentials_available"] is True

    @patch("core.auth.claude_discovery.discover_claude_credentials")
    @patch("core.cognition.pipeline.dispatch.get_provider_registry")
    def test_status_when_disconnected(self, mock_reg, mock_discover):
        registry = MagicMock()
        registry.get_default_name.return_value = "local"
        registry.list_all.return_value = ["local"]
        mock_reg.return_value = registry
        mock_discover.return_value = None

        client = _make_test_client()
        resp = client.get("/api/auth/claude/status")
        data = resp.json()
        assert data["connected"] is False
        assert data["credentials_available"] is False


class TestClaudeDisconnect:
    @patch("core.cognition.pipeline.dispatch.get_provider_registry")
    def test_disconnect_resets_default(self, mock_reg):
        registry = MagicMock()
        registry.get_default_name.return_value = "anthropic-oauth"
        mock_reg.return_value = registry

        client = _make_test_client()
        resp = client.post("/api/auth/claude/disconnect")
        assert resp.status_code == 200
        assert resp.json()["disconnected"] is True
        registry.set_default.assert_called_once_with("local")
