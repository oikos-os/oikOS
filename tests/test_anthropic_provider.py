"""Tests for AnthropicProvider — Anthropic Messages API via SDK."""

from unittest.mock import MagicMock, patch

import pytest

from core.cognition.providers.anthropic_provider import AnthropicProvider
from core.interface.models import CompletionResponse, ProviderMessage


@pytest.fixture
def provider():
    with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key-123"}):
        return AnthropicProvider(default_model="claude-sonnet-4-20250514")


def _mock_message_response(text="Hello!", model="claude-sonnet-4-20250514"):
    resp = MagicMock()
    resp.content = [MagicMock(type="text", text=text)]
    resp.model = model
    resp.usage = MagicMock(input_tokens=15, output_tokens=8)
    resp.stop_reason = "end_turn"
    return resp


def _mock_stream_events(text="Hello!"):
    events = []
    for char in text:
        event = MagicMock()
        event.type = "content_block_delta"
        event.delta = MagicMock(type="text_delta", text=char)
        events.append(event)
    return events


class TestAnthropicGenerate:
    def test_generate_basic(self, provider):
        mock_resp = _mock_message_response("Test output")
        with patch.object(provider._client.messages, "create", return_value=mock_resp):
            msgs = [ProviderMessage(role="user", content="Say hello")]
            result = provider.generate(msgs)
        assert isinstance(result, CompletionResponse)
        assert result.text == "Test output"
        assert result.provider == "anthropic"
        assert result.input_tokens == 15
        assert result.output_tokens == 8

    def test_generate_extracts_system_prompt(self, provider):
        mock_resp = _mock_message_response("I am oikOS")
        with patch.object(provider._client.messages, "create", return_value=mock_resp) as mock_create:
            msgs = [
                ProviderMessage(role="system", content="You are oikOS"),
                ProviderMessage(role="user", content="Who are you?"),
            ]
            provider.generate(msgs)
            call_kwargs = mock_create.call_args[1]
            assert call_kwargs["system"] == "You are oikOS"
            api_msgs = call_kwargs["messages"]
            assert all(m["role"] != "system" for m in api_msgs)

    def test_generate_no_system_prompt(self, provider):
        mock_resp = _mock_message_response("hi")
        with patch.object(provider._client.messages, "create", return_value=mock_resp) as mock_create:
            msgs = [ProviderMessage(role="user", content="hi")]
            provider.generate(msgs)
            call_kwargs = mock_create.call_args[1]
            assert "system" not in call_kwargs

    def test_generate_with_model_override(self, provider):
        mock_resp = _mock_message_response("hi", model="claude-opus-4-20250514")
        with patch.object(provider._client.messages, "create", return_value=mock_resp) as mock_create:
            msgs = [ProviderMessage(role="user", content="hi")]
            provider.generate(msgs, model="claude-opus-4-20250514")
            assert mock_create.call_args[1]["model"] == "claude-opus-4-20250514"

    def test_generate_error_returns_error_response(self, provider):
        with patch.object(provider._client.messages, "create", side_effect=Exception("rate limited")):
            msgs = [ProviderMessage(role="user", content="hi")]
            result = provider.generate(msgs)
            assert "[INFERENCE ERROR" in result.text


class TestAnthropicStream:
    def test_stream_yields_text_deltas(self, provider):
        events = _mock_stream_events("Hi!")
        mock_stream = MagicMock()
        mock_stream.__enter__ = MagicMock(return_value=iter(events))
        mock_stream.__exit__ = MagicMock(return_value=False)
        with patch.object(provider._client.messages, "stream", return_value=mock_stream):
            msgs = [ProviderMessage(role="user", content="hi")]
            chunks = list(provider.stream(msgs))
            assert "".join(chunks) == "Hi!"

    def test_stream_error_yields_nothing(self, provider):
        with patch.object(provider._client.messages, "stream", side_effect=Exception("timeout")):
            msgs = [ProviderMessage(role="user", content="hi")]
            chunks = list(provider.stream(msgs))
            assert chunks == []


class TestAnthropicMisc:
    def test_provider_name(self, provider):
        assert provider.provider_name == "anthropic"

    def test_count_tokens(self, provider):
        count = provider.count_tokens("one two three four five")
        assert count == 6

    def test_is_available_with_key(self, provider):
        assert provider.is_available() is True

    def test_is_available_no_key(self):
        p = AnthropicProvider(default_model="claude-sonnet-4-20250514", api_key="")
        assert p.is_available() is False

    def test_satisfies_protocol(self, provider):
        from core.cognition.providers.protocol import InferenceProvider
        assert isinstance(provider, InferenceProvider)
