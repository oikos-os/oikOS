"""Tests for OllamaProvider — httpx to Ollama OpenAI-compatible endpoint."""

import json
from unittest.mock import MagicMock, patch

import pytest

from core.cognition.providers.ollama_provider import OllamaProvider
from core.interface.models import CompletionResponse, ProviderMessage


@pytest.fixture
def provider():
    return OllamaProvider(
        base_url="http://localhost:11434",
        default_model="qwen2.5:14b",
        timeout=10,
    )


def _mock_chat_response(content="Hello!", model="qwen2.5:14b"):
    return {
        "id": "chatcmpl-123",
        "object": "chat.completion",
        "model": model,
        "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    }


def _mock_stream_lines(content="Hello!", model="qwen2.5:14b"):
    lines = []
    for char in content:
        chunk = {
            "id": "chatcmpl-123",
            "object": "chat.completion.chunk",
            "model": model,
            "choices": [{"index": 0, "delta": {"content": char}, "finish_reason": None}],
        }
        lines.append(f"data: {json.dumps(chunk)}")
    final = {
        "id": "chatcmpl-123",
        "object": "chat.completion.chunk",
        "model": model,
        "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 10, "completion_tokens": len(content), "total_tokens": 10 + len(content)},
    }
    lines.append(f"data: {json.dumps(final)}")
    lines.append("data: [DONE]")
    return lines


class TestOllamaProviderGenerate:
    def test_generate_basic(self, provider):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = _mock_chat_response("Test response")
        mock_resp.raise_for_status = MagicMock()

        with patch.object(provider._client, "post", return_value=mock_resp):
            msgs = [ProviderMessage(role="user", content="Say hello")]
            result = provider.generate(msgs)

        assert isinstance(result, CompletionResponse)
        assert result.text == "Test response"
        assert result.provider == "ollama"
        assert result.input_tokens == 10
        assert result.output_tokens == 5

    def test_generate_with_system_message(self, provider):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = _mock_chat_response("I am oikOS")
        mock_resp.raise_for_status = MagicMock()

        with patch.object(provider._client, "post", return_value=mock_resp) as mock_post:
            msgs = [
                ProviderMessage(role="system", content="You are oikOS"),
                ProviderMessage(role="user", content="Who are you?"),
            ]
            provider.generate(msgs)

            call_body = mock_post.call_args[1]["json"]
            assert call_body["messages"][0]["role"] == "system"
            assert call_body["messages"][0]["content"] == "You are oikOS"

    def test_generate_with_model_override(self, provider):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = _mock_chat_response("hi", model="qwen2.5:7b")
        mock_resp.raise_for_status = MagicMock()

        with patch.object(provider._client, "post", return_value=mock_resp) as mock_post:
            msgs = [ProviderMessage(role="user", content="hi")]
            provider.generate(msgs, model="qwen2.5:7b")
            call_body = mock_post.call_args[1]["json"]
            assert call_body["model"] == "qwen2.5:7b"

    def test_generate_error_returns_error_response(self, provider):
        with patch.object(provider._client, "post", side_effect=Exception("Connection refused")):
            msgs = [ProviderMessage(role="user", content="hi")]
            result = provider.generate(msgs)
            assert "[INFERENCE ERROR" in result.text
            assert result.output_tokens == 0


class TestOllamaProviderStream:
    def test_stream_yields_deltas(self, provider):
        lines = _mock_stream_lines("Hi!")

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.iter_lines.return_value = iter(lines)
        mock_resp.raise_for_status = MagicMock()
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch.object(provider._client, "stream", return_value=mock_resp):
            msgs = [ProviderMessage(role="user", content="hi")]
            chunks = list(provider.stream(msgs))
            assert "".join(chunks) == "Hi!"

    def test_stream_error_yields_nothing(self, provider):
        with patch.object(provider._client, "stream", side_effect=Exception("timeout")):
            msgs = [ProviderMessage(role="user", content="hi")]
            chunks = list(provider.stream(msgs))
            assert chunks == []


class TestOllamaProviderMisc:
    def test_provider_name(self, provider):
        assert provider.provider_name == "ollama"

    def test_count_tokens(self, provider):
        count = provider.count_tokens("one two three four five")
        assert count == 6  # 5 * 1.3 = 6.5 → int = 6

    def test_is_available_success(self, provider):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()

        with patch.object(provider._client, "get", return_value=mock_resp):
            assert provider.is_available() is True

    def test_is_available_failure(self, provider):
        with patch.object(provider._client, "get", side_effect=Exception("refused")):
            assert provider.is_available() is False

    def test_satisfies_protocol(self, provider):
        from core.cognition.providers.protocol import InferenceProvider
        assert isinstance(provider, InferenceProvider)
