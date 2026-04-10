"""Tests for ProviderRegistry — provider registration and lookup."""

import pytest

from core.cognition.providers.registry import ProviderRegistry
from core.interface.models import CompletionResponse, ProviderMessage


class _FakeProvider:
    provider_name = "fake"
    def generate(self, messages, **kw):
        return CompletionResponse(text="fake", model="f", provider="fake")
    def stream(self, messages, **kw):
        yield "fake"
    def count_tokens(self, text):
        return len(text.split())
    def is_available(self):
        return True


class _UnavailableProvider:
    provider_name = "down"
    def generate(self, messages, **kw):
        return CompletionResponse(text="", model="d", provider="down")
    def stream(self, messages, **kw):
        yield ""
    def count_tokens(self, text):
        return 0
    def is_available(self):
        return False


def test_register_and_get():
    reg = ProviderRegistry()
    provider = _FakeProvider()
    reg.register("fake", provider)
    assert reg.get("fake") is provider


def test_get_unknown_raises():
    reg = ProviderRegistry()
    with pytest.raises(KeyError, match="Unknown provider"):
        reg.get("nonexistent")


def test_register_sets_default_if_first():
    reg = ProviderRegistry()
    provider = _FakeProvider()
    reg.register("fake", provider)
    assert reg.get_default() is provider


def test_set_default():
    reg = ProviderRegistry()
    p1 = _FakeProvider()
    p2 = _FakeProvider()
    p2.provider_name = "fake2"
    reg.register("fake", p1)
    reg.register("fake2", p2)
    reg.set_default("fake2")
    assert reg.get_default() is p2


def test_set_default_unknown_raises():
    reg = ProviderRegistry()
    with pytest.raises(KeyError):
        reg.set_default("nonexistent")


def test_list_available():
    reg = ProviderRegistry()
    reg.register("up", _FakeProvider())
    reg.register("down", _UnavailableProvider())
    available = reg.list_available()
    assert "up" in available
    assert "down" not in available


def test_list_all():
    reg = ProviderRegistry()
    reg.register("a", _FakeProvider())
    reg.register("b", _FakeProvider())
    assert sorted(reg.list_all()) == ["a", "b"]


def test_get_default_empty_raises():
    reg = ProviderRegistry()
    with pytest.raises(ValueError, match="No providers registered"):
        reg.get_default()


def test_get_default_name():
    reg = ProviderRegistry()
    assert reg.get_default_name() is None
    reg.register("local", _FakeProvider())
    assert reg.get_default_name() == "local"
