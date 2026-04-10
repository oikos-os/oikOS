"""Tests for Claude Code identity headers and AnthropicOAuthProvider."""

import json
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

from core.auth.claude_discovery import ClaudeCredentials, RefreshedToken
from core.interface.models import ProviderMessage


def _make_creds(**overrides) -> ClaudeCredentials:
    defaults = {
        "access_token": "sk-ant-oat01-test",
        "refresh_token": "sk-ant-ort01-test",
        "expires_at": (time.time() + 3600) * 1000,
        "scopes": ["user:inference"],
        "subscription_type": "max",
        "source_path": "/fake/.credentials.json",
    }
    defaults.update(overrides)
    return ClaudeCredentials(**defaults)


class TestClaudeHeaders:
    def test_loads_from_toml(self):
        from core.auth.claude_headers import load_claude_headers

        headers = load_claude_headers()
        assert "anthropic-beta" in headers
        assert "anthropic-version" in headers
        assert "user-agent" in headers

    def test_defaults_include_oauth_beta(self):
        from core.auth.claude_headers import _DEFAULTS

        assert "oauth-2025-04-20" in _DEFAULTS["anthropic-beta"]
        assert "claude-code-20250219" in _DEFAULTS["anthropic-beta"]
        assert "interleaved-thinking-2025-05-14" in _DEFAULTS["anthropic-beta"]

    def test_get_headers_includes_bearer(self):
        from core.auth.claude_headers import get_claude_code_headers

        headers = get_claude_code_headers("sk-ant-oat01-test")
        assert headers["Authorization"] == "Bearer sk-ant-oat01-test"
        assert headers["Content-Type"] == "application/json"
        assert "anthropic-beta" in headers

    def test_falls_back_to_defaults_on_missing_toml(self):
        from core.auth.claude_headers import _DEFAULTS, load_claude_headers

        with patch("core.auth.claude_headers._TOML_PATH", Path("/nonexistent/path.toml")):
            headers = load_claude_headers()
            assert headers == _DEFAULTS


class TestOAuthRequestFormat:
    """Verify the OAuth request body includes required fields for all Claude models."""

    def test_build_system_includes_billing_header(self):
        from core.auth.claude_provider import _build_system

        blocks = _build_system(None)
        assert len(blocks) == 1
        assert "x-anthropic-billing-header" in blocks[0]["text"]

    def test_build_system_appends_user_prompt(self):
        from core.auth.claude_provider import _build_system

        blocks = _build_system("You are helpful")
        assert len(blocks) == 2
        assert "x-anthropic-billing-header" in blocks[0]["text"]
        assert blocks[1]["text"] == "You are helpful"

    def test_build_oauth_headers(self):
        from core.auth.claude_provider import _build_oauth_headers

        headers = _build_oauth_headers("sk-ant-oat01-test")
        assert headers["Authorization"] == "Bearer sk-ant-oat01-test"
        assert "oauth-2025-04-20" in headers["anthropic-beta"]
        assert "claude-code-20250219" in headers["anthropic-beta"]
        assert "interleaved-thinking-2025-05-14" in headers["anthropic-beta"]
        assert "claude-code" in headers["user-agent"]

    def test_api_url_has_beta_param(self):
        from core.auth.claude_provider import _API_URL

        assert "?beta=true" in _API_URL


class TestAnthropicOAuthProvider:
    def test_provider_name(self):
        from core.auth.claude_provider import AnthropicOAuthProvider

        p = AnthropicOAuthProvider(_make_creds())
        assert p.provider_name == "anthropic-oauth"

    def test_is_available_with_valid_creds(self):
        from core.auth.claude_provider import AnthropicOAuthProvider

        p = AnthropicOAuthProvider(_make_creds())
        assert p.is_available() is True

    def test_is_available_false_when_expired(self):
        from core.auth.claude_provider import AnthropicOAuthProvider

        p = AnthropicOAuthProvider(_make_creds(expires_at=0))
        assert p.is_available() is False

    def test_count_tokens(self):
        from core.auth.claude_provider import AnthropicOAuthProvider

        p = AnthropicOAuthProvider(_make_creds())
        assert isinstance(p.count_tokens("hello world"), int)
        assert p.count_tokens("hello world") > 0

    def test_generate_returns_completion(self):
        from core.auth.claude_provider import AnthropicOAuthProvider

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "content": [{"type": "text", "text": "Hello from Claude"}],
            "model": "claude-sonnet-4-20250514",
            "usage": {"input_tokens": 10, "output_tokens": 5},
        }

        p = AnthropicOAuthProvider(_make_creds())
        p._client = MagicMock()
        p._client.post.return_value = mock_response

        result = p.generate([ProviderMessage(role="user", content="Hi")])

        assert result.text == "Hello from Claude"
        assert result.provider == "anthropic-oauth"
        assert result.input_tokens == 10
        p._client.post.assert_called_once()
        body = json.loads(p._client.post.call_args.kwargs["content"])
        assert "messages" in body

    def test_generate_body_includes_thinking(self):
        from core.auth.claude_provider import AnthropicOAuthProvider

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "content": [{"type": "text", "text": "ok"}],
            "model": "claude-sonnet-4-20250514",
            "usage": {"input_tokens": 10, "output_tokens": 5},
        }

        p = AnthropicOAuthProvider(_make_creds())
        p._client = MagicMock()
        p._client.post.return_value = mock_response

        p.generate([ProviderMessage(role="user", content="Hi")])

        body = json.loads(p._client.post.call_args.kwargs["content"])
        assert "thinking" in body
        assert body["thinking"]["type"] == "enabled"
        assert body["thinking"]["budget_tokens"] >= 1024

    def test_generate_body_includes_billing_system(self):
        from core.auth.claude_provider import AnthropicOAuthProvider

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "content": [{"type": "text", "text": "ok"}],
            "model": "claude-sonnet-4-20250514",
            "usage": {"input_tokens": 10, "output_tokens": 5},
        }

        p = AnthropicOAuthProvider(_make_creds())
        p._client = MagicMock()
        p._client.post.return_value = mock_response

        p.generate([ProviderMessage(role="user", content="Hi")])

        body = json.loads(p._client.post.call_args.kwargs["content"])
        assert isinstance(body["system"], list)
        assert "x-anthropic-billing-header" in body["system"][0]["text"]

    def test_generate_extracts_system_message(self):
        from core.auth.claude_provider import AnthropicOAuthProvider

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "content": [{"type": "text", "text": "ok"}],
            "model": "claude-sonnet-4-20250514",
            "usage": {"input_tokens": 10, "output_tokens": 5},
        }

        p = AnthropicOAuthProvider(_make_creds())
        p._client = MagicMock()
        p._client.post.return_value = mock_response

        msgs = [
            ProviderMessage(role="system", content="You are helpful"),
            ProviderMessage(role="user", content="Hi"),
        ]
        p.generate(msgs)

        body = json.loads(p._client.post.call_args.kwargs["content"])
        # Billing block + user system prompt
        assert len(body["system"]) == 2
        assert body["system"][1]["text"] == "You are helpful"
        assert all(m["role"] != "system" for m in body["messages"])

    def test_generate_handles_http_error(self):
        from core.auth.claude_provider import AnthropicOAuthProvider

        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"

        p = AnthropicOAuthProvider(_make_creds())
        p._client = MagicMock()
        p._client.post.return_value = mock_response

        result = p.generate([ProviderMessage(role="user", content="Hi")])
        assert result.text.startswith("[INFERENCE ERROR")

    def test_auto_refresh_when_near_expiry(self):
        from core.auth.claude_provider import AnthropicOAuthProvider

        near_expiry = (time.time() + 120) * 1000
        creds = _make_creds(expires_at=near_expiry)

        refreshed = RefreshedToken(
            access_token="sk-ant-oat01-refreshed",
            expires_at=(time.time() + 3600) * 1000,
        )

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "content": [{"type": "text", "text": "ok"}],
            "model": "claude-sonnet-4-20250514",
            "usage": {"input_tokens": 5, "output_tokens": 3},
        }

        with patch("core.auth.claude_provider.refresh_access_token", return_value=refreshed) as mock_refresh:
            p = AnthropicOAuthProvider(creds)
            p._client = MagicMock()
            p._client.post.return_value = mock_response

            p.generate([ProviderMessage(role="user", content="Hi")])

            mock_refresh.assert_called_once()
            assert p._credentials.access_token == "sk-ant-oat01-refreshed"

    def test_stream_yields_text_deltas(self):
        from core.auth.claude_provider import AnthropicOAuthProvider

        sse_lines = [
            'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"Hello"}}',
            'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":" world"}}',
            'data: [DONE]',
        ]

        mock_stream_response = MagicMock()
        mock_stream_response.__enter__ = MagicMock(return_value=mock_stream_response)
        mock_stream_response.__exit__ = MagicMock(return_value=False)
        mock_stream_response.iter_lines.return_value = iter(sse_lines)

        p = AnthropicOAuthProvider(_make_creds())
        p._client = MagicMock()
        p._client.stream.return_value = mock_stream_response

        chunks = list(p.stream([ProviderMessage(role="user", content="Hi")]))
        assert chunks == ["Hello", " world"]

    def test_stream_excludes_thinking_deltas(self):
        from core.auth.claude_provider import AnthropicOAuthProvider

        sse_lines = [
            'data: {"type":"content_block_delta","delta":{"type":"thinking_delta","thinking":"Let me think..."}}',
            'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"4"}}',
            'data: [DONE]',
        ]

        mock_stream_response = MagicMock()
        mock_stream_response.__enter__ = MagicMock(return_value=mock_stream_response)
        mock_stream_response.__exit__ = MagicMock(return_value=False)
        mock_stream_response.iter_lines.return_value = iter(sse_lines)

        p = AnthropicOAuthProvider(_make_creds())
        p._client = MagicMock()
        p._client.stream.return_value = mock_stream_response

        chunks = list(p.stream([ProviderMessage(role="user", content="2+2?")]))
        assert chunks == ["4"]

    def test_stream_body_includes_thinking_and_billing(self):
        from core.auth.claude_provider import AnthropicOAuthProvider

        mock_stream_response = MagicMock()
        mock_stream_response.__enter__ = MagicMock(return_value=mock_stream_response)
        mock_stream_response.__exit__ = MagicMock(return_value=False)
        mock_stream_response.iter_lines.return_value = iter(['data: [DONE]'])

        p = AnthropicOAuthProvider(_make_creds())
        p._client = MagicMock()
        p._client.stream.return_value = mock_stream_response

        list(p.stream([ProviderMessage(role="user", content="Hi")]))

        body = json.loads(p._client.stream.call_args.kwargs["content"])
        assert body["stream"] is True
        assert body["thinking"]["type"] == "enabled"
        assert isinstance(body["system"], list)
        assert "x-anthropic-billing-header" in body["system"][0]["text"]

    def test_generate_filters_thinking_blocks_from_response(self):
        """Verify thinking blocks in response are excluded from text output."""
        from core.auth.claude_provider import AnthropicOAuthProvider

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "content": [
                {"type": "thinking", "thinking": "Let me think..."},
                {"type": "text", "text": "4"},
            ],
            "model": "claude-sonnet-4-20250514",
            "usage": {"input_tokens": 10, "output_tokens": 20},
        }

        p = AnthropicOAuthProvider(_make_creds())
        p._client = MagicMock()
        p._client.post.return_value = mock_response

        result = p.generate([ProviderMessage(role="user", content="2+2?")])
        assert result.text == "4"


class TestBootstrapIntegration:
    @patch("core.auth.claude_discovery.discover_claude_credentials")
    def test_registers_oauth_when_credentials_found(self, mock_discover):
        mock_discover.return_value = _make_creds()

        from core.cognition.providers.bootstrap import _try_register_oauth
        from core.cognition.providers.registry import ProviderRegistry

        reg = ProviderRegistry()
        _try_register_oauth(reg)

        assert "anthropic-oauth" in reg.list_all()

    @patch("core.auth.claude_discovery.discover_claude_credentials")
    def test_skips_oauth_when_no_credentials(self, mock_discover):
        mock_discover.return_value = None

        from core.cognition.providers.bootstrap import _try_register_oauth
        from core.cognition.providers.registry import ProviderRegistry

        reg = ProviderRegistry()
        _try_register_oauth(reg)

        assert "anthropic-oauth" not in reg.list_all()
