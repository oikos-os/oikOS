"""Tests for InferenceProvider Protocol and message types."""

from typing import Iterator

import pytest

from core.cognition.providers.protocol import InferenceProvider
from core.interface.models import (
    CompletionResponse,
    DataTier,
    ProviderMessage,
    RoutingPosture,
)


class _StubProvider:
    """Minimal provider that satisfies the Protocol."""
    provider_name = "stub"

    def generate(self, messages, *, model=None, temperature=0.7, max_tokens=2048, **kw):
        return CompletionResponse(
            text="hello", model="stub-1", provider="stub",
            input_tokens=5, output_tokens=1, latency_ms=10,
        )

    def stream(self, messages, *, model=None, temperature=0.7, max_tokens=2048, **kw):
        yield "hel"
        yield "lo"

    def count_tokens(self, text):
        return int(len(text.split()) * 1.3)

    def is_available(self):
        return True


def test_stub_satisfies_protocol():
    provider = _StubProvider()
    assert isinstance(provider, InferenceProvider)


def test_provider_message_creation():
    msg = ProviderMessage(role="user", content="hello")
    assert msg.role == "user"
    assert msg.content == "hello"
    assert msg.name is None


def test_provider_message_with_tool_name():
    msg = ProviderMessage(role="tool", content="result", name="search")
    assert msg.name == "search"


def test_completion_response_defaults():
    resp = CompletionResponse(text="hi", model="m", provider="p")
    assert resp.input_tokens == 0
    assert resp.output_tokens == 0
    assert resp.logprobs is None
    assert resp.raw == {}


def test_data_tier_values():
    assert DataTier.NEVER_LEAVE.value == "NEVER_LEAVE"
    assert DataTier.SENSITIVE.value == "SENSITIVE"
    assert DataTier.SAFE.value == "SAFE"


def test_routing_posture_values():
    assert RoutingPosture.CONSERVATIVE.value == "conservative"
    assert RoutingPosture.BALANCED.value == "balanced"
    assert RoutingPosture.AGGRESSIVE.value == "aggressive"


def test_stub_generate():
    p = _StubProvider()
    msgs = [ProviderMessage(role="user", content="hi")]
    resp = p.generate(msgs)
    assert resp.text == "hello"
    assert resp.provider == "stub"


def test_stub_stream():
    p = _StubProvider()
    msgs = [ProviderMessage(role="user", content="hi")]
    chunks = list(p.stream(msgs))
    assert "".join(chunks) == "hello"


def test_stub_count_tokens():
    p = _StubProvider()
    count = p.count_tokens("hello world")
    assert count == 2  # 2 words * 1.3 = 2.6 → int(2.6) = 2


def test_stub_is_available():
    p = _StubProvider()
    assert p.is_available() is True
