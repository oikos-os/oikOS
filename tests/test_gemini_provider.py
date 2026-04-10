"""Tests for GeminiProvider — wraps existing cloud.py as Protocol-compliant provider."""

from unittest.mock import patch

import pytest

from core.cognition.providers.gemini_provider import GeminiProvider
from core.interface.models import CloudResponse, CompletionResponse, ProviderMessage


@pytest.fixture
def provider():
    with patch.dict("os.environ", {"GEMINI_API_KEY": "test-key"}):
        return GeminiProvider(default_model="gemini-2.5-pro")


def test_provider_name(provider):
    assert provider.provider_name == "gemini"


def test_generate_delegates_to_send_to_cloud(provider):
    cloud_resp = CloudResponse(
        text="Gemini says hi", model="gemini-2.5-pro",
        input_tokens=20, output_tokens=10, latency_ms=500,
    )
    with patch("core.cognition.providers.gemini_provider.send_to_cloud", return_value=cloud_resp):
        msgs = [
            ProviderMessage(role="system", content="You are helpful"),
            ProviderMessage(role="user", content="Hello"),
        ]
        result = provider.generate(msgs)

    assert isinstance(result, CompletionResponse)
    assert result.text == "Gemini says hi"
    assert result.provider == "gemini"
    assert result.input_tokens == 20


def test_generate_extracts_system_and_query(provider):
    cloud_resp = CloudResponse(
        text="ok", model="gemini-2.5-pro",
        input_tokens=5, output_tokens=2, latency_ms=100,
    )
    with patch("core.cognition.providers.gemini_provider.send_to_cloud", return_value=cloud_resp) as mock_send:
        msgs = [
            ProviderMessage(role="system", content="Be concise"),
            ProviderMessage(role="user", content="What is 2+2?"),
        ]
        provider.generate(msgs)

        call_kwargs = mock_send.call_args
        assert call_kwargs[0][0] == "What is 2+2?"  # query is first positional arg
        assert call_kwargs[1]["system"] == "Be concise"


def test_generate_multi_message_context(provider):
    cloud_resp = CloudResponse(
        text="ok", model="gemini-2.5-pro",
        input_tokens=5, output_tokens=2, latency_ms=100,
    )
    with patch("core.cognition.providers.gemini_provider.send_to_cloud", return_value=cloud_resp) as mock_send:
        msgs = [
            ProviderMessage(role="user", content="First message"),
            ProviderMessage(role="assistant", content="First reply"),
            ProviderMessage(role="user", content="Second message"),
        ]
        provider.generate(msgs)

        call_args = mock_send.call_args
        assert call_args[0][0] == "Second message"  # last user = query


def test_generate_error(provider):
    with patch("core.cognition.providers.gemini_provider.send_to_cloud", side_effect=Exception("API error")):
        msgs = [ProviderMessage(role="user", content="hi")]
        result = provider.generate(msgs)
        assert "[INFERENCE ERROR" in result.text


def test_stream_delegates_to_stream_cloud(provider):
    with patch("core.cognition.providers.gemini_provider.stream_cloud", return_value=iter(["He", "llo"])):
        msgs = [ProviderMessage(role="user", content="hi")]
        chunks = list(provider.stream(msgs))
        assert "".join(chunks) == "Hello"


def test_stream_error(provider):
    with patch("core.cognition.providers.gemini_provider.stream_cloud", side_effect=Exception("timeout")):
        msgs = [ProviderMessage(role="user", content="hi")]
        chunks = list(provider.stream(msgs))
        assert chunks == []


def test_count_tokens(provider):
    assert provider.count_tokens("one two three") == 3  # 3 * 1.3 = 3.9 → int(3.9) = 3


def test_is_available_with_key(provider):
    assert provider.is_available() is True


def test_is_available_no_key():
    with patch.dict("os.environ", {"GEMINI_API_KEY": ""}):
        p = GeminiProvider()
        assert p.is_available() is False


def test_satisfies_protocol(provider):
    from core.cognition.providers.protocol import InferenceProvider
    assert isinstance(provider, InferenceProvider)
