"""Tests for OpenAI provider."""

import json
from unittest.mock import patch, MagicMock

import httpx
import pytest

from core.cognition.providers.openai_provider import OpenAIProvider
from core.interface.models import ProviderMessage


def _make_response(content="Hello!", model="gpt-4o", prompt_tokens=10, completion_tokens=5):
    """Build a mock OpenAI chat completion response."""
    return httpx.Response(
        200,
        json={
            "choices": [{"message": {"content": content}, "index": 0}],
            "model": model,
            "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens},
        },
        request=httpx.Request("POST", "https://api.openai.com/v1/chat/completions"),
    )


def _make_messages(text="Hi"):
    return [ProviderMessage(role="user", content=text)]


class TestGenerate:
    def test_success(self):
        provider = OpenAIProvider(api_key="test-key")
        with patch.object(provider._client, "post", return_value=_make_response()):
            resp = provider.generate(_make_messages())
        assert resp.text == "Hello!"
        assert resp.provider == "openai"
        assert resp.model == "gpt-4o"
        assert resp.input_tokens == 10
        assert resp.output_tokens == 5

    def test_model_override(self):
        provider = OpenAIProvider(api_key="test-key")
        with patch.object(provider._client, "post", return_value=_make_response()) as mock_post:
            provider.generate(_make_messages(), model="gpt-4o-mini")
        body = mock_post.call_args[1]["json"]
        assert body["model"] == "gpt-4o-mini"

    def test_error_masking_http_error(self):
        provider = OpenAIProvider(api_key="test-key")
        error_resp = httpx.Response(
            401,
            json={"error": {"message": "Invalid API key: sk-secret123"}},
            request=httpx.Request("POST", "https://api.openai.com/v1/chat/completions"),
        )
        with patch.object(provider._client, "post", return_value=error_resp):
            resp = provider.generate(_make_messages())
        assert resp.text == "[INFERENCE ERROR: provider unavailable]"
        assert "sk-secret" not in resp.text

    def test_error_masking_connection_error(self):
        provider = OpenAIProvider(api_key="test-key")
        with patch.object(provider._client, "post", side_effect=httpx.ConnectError("refused")):
            resp = provider.generate(_make_messages())
        assert resp.text == "[INFERENCE ERROR: provider unavailable]"


class TestStream:
    def test_yields_content(self):
        provider = OpenAIProvider(api_key="test-key")

        sse_lines = [
            'data: {"choices":[{"delta":{"content":"Hello"}}]}',
            'data: {"choices":[{"delta":{"content":" world"}}]}',
            "data: [DONE]",
        ]

        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.iter_lines = MagicMock(return_value=iter(sse_lines))
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch.object(provider._client, "stream", return_value=mock_resp):
            chunks = list(provider.stream(_make_messages()))
        assert chunks == ["Hello", " world"]

    def test_stream_error_yields_nothing(self):
        provider = OpenAIProvider(api_key="test-key")
        with patch.object(provider._client, "stream", side_effect=httpx.ConnectError("refused")):
            chunks = list(provider.stream(_make_messages()))
        assert chunks == []


class TestAvailability:
    def test_available_with_key(self):
        provider = OpenAIProvider(api_key="test-key")
        assert provider.is_available() is True

    def test_unavailable_without_key(self):
        with patch.dict("os.environ", {}, clear=True):
            provider = OpenAIProvider(api_key=None)
        assert provider.is_available() is False

    def test_key_from_env(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "env-key-123")
        provider = OpenAIProvider()
        assert provider.is_available() is True


class TestConfig:
    def test_provider_name(self):
        assert OpenAIProvider.provider_name == "openai"

    def test_custom_base_url(self):
        provider = OpenAIProvider(api_key="key", base_url="https://custom.api.com/v1/")
        assert provider._base_url == "https://custom.api.com/v1"

    def test_count_tokens(self):
        provider = OpenAIProvider(api_key="key")
        assert provider.count_tokens("hello world") == int(2 * 1.3)

    def test_default_model(self):
        provider = OpenAIProvider(api_key="key", default_model="gpt-3.5-turbo")
        assert provider._default_model == "gpt-3.5-turbo"
