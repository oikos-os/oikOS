"""Integration tests — classifier scope in router routing decisions."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from core.cognition.providers.content_classifier import ContentClassifier
from core.interface.models import DataTier, ProviderMessage


class TestRouterUsesUserInputScope:
    """Router should classify only user messages for routing decisions."""

    def test_safe_query_with_identity_system_prompt_routes_to_cloud(self):
        """A safe user query should route to cloud even if system prompt has TELOS."""
        from core.cognition.providers.router import PrivacyAwareRouter
        from core.cognition.providers.registry import ProviderRegistry

        registry = ProviderRegistry()
        local_mock = MagicMock()
        local_mock.generate.return_value = MagicMock(text="local response", provider="local", model="qwen2.5:14b", input_tokens=10, output_tokens=10, latency_ms=100)
        cloud_mock = MagicMock()
        cloud_mock.generate.return_value = MagicMock(text="cloud response", provider="gemini", model="gemini-2.5-pro", input_tokens=10, output_tokens=10, latency_ms=200)
        cloud_mock.is_available.return_value = True

        registry.register("local", local_mock)
        registry.register("gemini", cloud_mock)

        router = PrivacyAwareRouter(registry=registry, local_name="local")

        messages = [
            ProviderMessage(role="system", content="You are KAIROS. Source: vault/identity/TELOS_01.md. MISSION.md loaded."),
            ProviderMessage(role="user", content="What is the capital of France?"),
        ]

        pii_result = MagicMock(has_pii=False, entities=[])
        with patch("core.safety.pii.detect_pii", return_value=pii_result):
            result = router.route(messages, provider="gemini")

        # Should route to cloud, not be blocked by NEVER_LEAVE
        cloud_mock.generate.assert_called_once()
        assert result.text == "cloud response"

    def test_never_leave_user_query_blocked_from_cloud(self):
        """User query with TELOS should be blocked from cloud."""
        from core.cognition.providers.router import PrivacyAwareRouter
        from core.cognition.providers.registry import ProviderRegistry

        registry = ProviderRegistry()
        local_mock = MagicMock()
        local_mock.generate.return_value = MagicMock(text="local response", provider="local", model="qwen2.5:14b", input_tokens=10, output_tokens=10, latency_ms=100)
        cloud_mock = MagicMock()
        cloud_mock.is_available.return_value = True

        registry.register("local", local_mock)
        registry.register("gemini", cloud_mock)

        router = PrivacyAwareRouter(registry=registry, local_name="local")

        messages = [
            ProviderMessage(role="system", content="General assistant."),
            ProviderMessage(role="user", content="What does my TELOS say about purpose?"),
        ]

        result = router.route(messages, provider="gemini")

        # Should be forced local — user query contains NEVER_LEAVE pattern
        local_mock.generate.assert_called_once()
        cloud_mock.generate.assert_not_called()

    def test_stream_safe_query_not_blocked(self):
        """Streaming: safe user query with identity system prompt should not be blocked."""
        from core.cognition.providers.router import PrivacyAwareRouter
        from core.cognition.providers.registry import ProviderRegistry

        registry = ProviderRegistry()
        local_mock = MagicMock()
        cloud_mock = MagicMock()
        cloud_mock.is_available.return_value = True
        cloud_mock.stream.return_value = iter(["hello", " world"])

        registry.register("local", local_mock)
        registry.register("gemini", cloud_mock)

        router = PrivacyAwareRouter(registry=registry, local_name="local")

        messages = [
            ProviderMessage(role="system", content="vault/identity/TELOS loaded. MISSION.md active."),
            ProviderMessage(role="user", content="Hello!"),
        ]

        pii_result = MagicMock(has_pii=False, entities=[])
        with patch("core.safety.pii.detect_pii", return_value=pii_result):
            chunks = list(router.route_stream(messages, provider="gemini"))

        cloud_mock.stream.assert_called_once()
        assert chunks == ["hello", " world"]

    def test_api_key_in_user_query_blocked(self):
        """User pasting a credential should be blocked from cloud."""
        from core.cognition.providers.router import PrivacyAwareRouter
        from core.cognition.providers.registry import ProviderRegistry

        registry = ProviderRegistry()
        local_mock = MagicMock()
        local_mock.generate.return_value = MagicMock(text="blocked", provider="local", model="qwen2.5:14b", input_tokens=10, output_tokens=10, latency_ms=50)
        cloud_mock = MagicMock()
        cloud_mock.is_available.return_value = True

        registry.register("local", local_mock)
        registry.register("gemini", cloud_mock)

        router = PrivacyAwareRouter(registry=registry, local_name="local")

        messages = [
            ProviderMessage(role="system", content="You are a helpful assistant."),
            ProviderMessage(role="user", content="My API key is sk-" + "1234567890abcdefghij"),
        ]

        result = router.route(messages, provider="gemini")

        local_mock.generate.assert_called_once()
        cloud_mock.generate.assert_not_called()

    def test_filter_cloud_context_strips_identity(self):
        """_filter_cloud_context excludes CORE and EPISODIC tier slices."""
        from core.cognition.pipeline.dispatch import filter_cloud_context as _filter_cloud_context
        from core.interface.models import CompiledContext, ContextSlice, MemoryTier

        compiled = CompiledContext(
            query="test",
            slices=[
                ContextSlice(name="core", tier=MemoryTier.CORE, fragments=["TELOS identity data"], token_count=50),
                ContextSlice(name="episodic", tier=MemoryTier.EPISODIC, fragments=["session history"], token_count=30),
                ContextSlice(name="semantic", tier=MemoryTier.SEMANTIC, fragments=["quantum computing facts"], token_count=40),
            ],
            total_tokens=120,
            budget=6000,
        )
        result = _filter_cloud_context(compiled)
        assert "TELOS" not in result
        assert "session history" not in result
        assert "quantum computing" in result
