"""Tests for EmbedderRegistry and embedder.py delegation layer.

Proves the system works when NO embedder is registered (graceful degradation),
when an embedder IS registered (delegation), and when an embedder throws
exceptions at runtime (safe fallback).
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from core.interface.config import EMBED_DIMS


# ── Fixtures ─────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _reset_registry():
    """Reset the EmbedderRegistry singleton before each test."""
    from core.memory.embedder_registry import EmbedderRegistry

    EmbedderRegistry.reset()
    yield
    EmbedderRegistry.reset()


def _make_mock_provider(
    *,
    available: bool = True,
    single_result: list[float] | None = None,
    batch_result: list[list[float]] | None = None,
):
    """Create a mock EmbedderProvider with controllable behavior."""
    provider = MagicMock()
    provider.provider_name = "mock"
    provider.dims = EMBED_DIMS
    provider.is_available.return_value = available
    if single_result is not None:
        provider.embed_single.return_value = single_result
    else:
        provider.embed_single.return_value = [0.5] * EMBED_DIMS
    if batch_result is not None:
        provider.embed_batch.return_value = batch_result
    else:
        provider.embed_batch.return_value = [[0.5] * EMBED_DIMS]
    return provider


# ── TestNoEmbedder ───────────────────────────────────────────────────────


class TestNoEmbedder:
    """System behavior when NO embedder is registered."""

    def test_embed_single_returns_zero_vector(self):
        from core.memory.embedder import embed_single

        result = embed_single("hello world")
        assert len(result) == EMBED_DIMS
        assert all(v == 0.0 for v in result)

    def test_embed_batch_returns_zero_vectors(self):
        from core.memory.embedder import embed_batch

        result = embed_batch(["a", "b"])
        assert len(result) == 2
        assert all(len(v) == EMBED_DIMS for v in result)
        assert all(v == 0.0 for v in result[0])
        assert all(v == 0.0 for v in result[1])

    def test_check_health_returns_false(self):
        from core.memory.embedder import check_health

        assert check_health() is False

    def test_embed_single_safe_returns_none(self):
        from core.memory.embedder_registry import EmbedderRegistry

        result = EmbedderRegistry.get_instance().embed_single_safe("text")
        assert result is None

    def test_embed_batch_safe_returns_none(self):
        from core.memory.embedder_registry import EmbedderRegistry

        result = EmbedderRegistry.get_instance().embed_batch_safe(["a"])
        assert result is None

    def test_is_available_returns_false(self):
        from core.memory.embedder_registry import EmbedderRegistry

        assert EmbedderRegistry.get_instance().is_available() is False


# ── TestEmbedderRegistered ───────────────────────────────────────────────


class TestEmbedderRegistered:
    """System behavior when a working embedder IS registered."""

    def test_embed_single_delegates_to_provider(self):
        from core.memory.embedder import embed_single
        from core.memory.embedder_registry import EmbedderRegistry

        expected = [0.42] * EMBED_DIMS
        provider = _make_mock_provider(single_result=expected)
        EmbedderRegistry.get_instance().register(provider)

        result = embed_single("test query")
        assert result == expected
        provider.embed_single.assert_called_once_with("test query")

    def test_embed_batch_delegates_to_provider(self):
        from core.memory.embedder import embed_batch
        from core.memory.embedder_registry import EmbedderRegistry

        expected = [[0.1] * EMBED_DIMS, [0.2] * EMBED_DIMS]
        provider = _make_mock_provider(batch_result=expected)
        EmbedderRegistry.get_instance().register(provider)

        result = embed_batch(["hello", "world"])
        assert result == expected
        provider.embed_batch.assert_called_once_with(["hello", "world"])

    def test_check_health_returns_true_when_available(self):
        from core.memory.embedder import check_health
        from core.memory.embedder_registry import EmbedderRegistry

        provider = _make_mock_provider(available=True)
        EmbedderRegistry.get_instance().register(provider)

        assert check_health() is True

    def test_check_health_returns_false_when_unavailable(self):
        from core.memory.embedder import check_health
        from core.memory.embedder_registry import EmbedderRegistry

        provider = _make_mock_provider(available=False)
        EmbedderRegistry.get_instance().register(provider)

        assert check_health() is False

    def test_is_available_delegates_to_provider(self):
        from core.memory.embedder_registry import EmbedderRegistry

        provider = _make_mock_provider(available=True)
        EmbedderRegistry.get_instance().register(provider)

        assert EmbedderRegistry.get_instance().is_available() is True
        provider.is_available.assert_called()

    def test_get_returns_provider(self):
        from core.memory.embedder_registry import EmbedderRegistry

        provider = _make_mock_provider()
        registry = EmbedderRegistry.get_instance()
        registry.register(provider)

        assert registry.get() is provider

    def test_get_returns_none_before_register(self):
        from core.memory.embedder_registry import EmbedderRegistry

        assert EmbedderRegistry.get_instance().get() is None


# ── TestEmbedderUnavailableDuringUse ─────────────────────────────────────


class TestEmbedderUnavailableDuringUse:
    """System behavior when a registered embedder throws at runtime."""

    def test_embed_single_safe_catches_exception(self):
        from core.memory.embedder_registry import EmbedderRegistry

        provider = _make_mock_provider()
        provider.embed_single.side_effect = Exception("Connection refused")
        EmbedderRegistry.get_instance().register(provider)

        result = EmbedderRegistry.get_instance().embed_single_safe("text")
        assert result is None

    def test_embed_batch_safe_catches_exception(self):
        from core.memory.embedder_registry import EmbedderRegistry

        provider = _make_mock_provider()
        provider.embed_batch.side_effect = RuntimeError("Ollama crashed")
        EmbedderRegistry.get_instance().register(provider)

        result = EmbedderRegistry.get_instance().embed_batch_safe(["a", "b"])
        assert result is None

    def test_embed_single_returns_zero_vector_on_exception(self):
        """The delegation layer in embedder.py converts None -> zero-vector."""
        from core.memory.embedder import embed_single
        from core.memory.embedder_registry import EmbedderRegistry

        provider = _make_mock_provider()
        provider.embed_single.side_effect = Exception("Timeout")
        EmbedderRegistry.get_instance().register(provider)

        result = embed_single("hello")
        assert len(result) == EMBED_DIMS
        assert all(v == 0.0 for v in result)

    def test_embed_batch_returns_zero_vectors_on_exception(self):
        """The delegation layer in embedder.py converts None -> zero-vectors."""
        from core.memory.embedder import embed_batch
        from core.memory.embedder_registry import EmbedderRegistry

        provider = _make_mock_provider()
        provider.embed_batch.side_effect = Exception("OOM")
        EmbedderRegistry.get_instance().register(provider)

        result = embed_batch(["a", "b", "c"])
        assert len(result) == 3
        assert all(len(v) == EMBED_DIMS for v in result)
        assert all(all(x == 0.0 for x in v) for v in result)

    def test_is_available_catches_exception(self):
        """is_available() should not propagate provider exceptions."""
        from core.memory.embedder_registry import EmbedderRegistry

        provider = _make_mock_provider()
        provider.is_available.side_effect = Exception("Network error")
        EmbedderRegistry.get_instance().register(provider)

        assert EmbedderRegistry.get_instance().is_available() is False


# ── TestSingleton ────────────────────────────────────────────────────────


class TestSingleton:
    """EmbedderRegistry singleton behavior."""

    def test_get_instance_returns_same_object(self):
        from core.memory.embedder_registry import EmbedderRegistry

        a = EmbedderRegistry.get_instance()
        b = EmbedderRegistry.get_instance()
        assert a is b

    def test_reset_clears_singleton(self):
        from core.memory.embedder_registry import EmbedderRegistry

        a = EmbedderRegistry.get_instance()
        EmbedderRegistry.reset()
        b = EmbedderRegistry.get_instance()
        assert a is not b

    def test_reset_clears_provider(self):
        from core.memory.embedder_registry import EmbedderRegistry

        provider = _make_mock_provider()
        EmbedderRegistry.get_instance().register(provider)
        assert EmbedderRegistry.get_instance().get() is provider

        EmbedderRegistry.reset()
        assert EmbedderRegistry.get_instance().get() is None
