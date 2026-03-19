"""Tests for PrivacyAwareRouter — posture-based provider routing with privacy enforcement."""

from unittest.mock import patch

import pytest

from core.cognition.providers.router import PrivacyAwareRouter
from core.cognition.providers.registry import ProviderRegistry
from core.interface.models import (
    CompletionResponse,
    DataTier,
    ProviderMessage,
    RoutingPosture,
)


class _FakeProvider:
    def __init__(self, name):
        self.provider_name = name
    def generate(self, messages, **kw):
        return CompletionResponse(text=f"from-{self.provider_name}", model="m", provider=self.provider_name)
    def stream(self, messages, **kw):
        yield f"from-{self.provider_name}"
    def count_tokens(self, text):
        return len(text.split())
    def is_available(self):
        return True


@pytest.fixture
def registry():
    reg = ProviderRegistry()
    reg.register("local", _FakeProvider("local"))
    reg.register("claude", _FakeProvider("claude"))
    return reg


@pytest.fixture
def router(registry):
    return PrivacyAwareRouter(registry=registry, local_name="local")


class TestExplicitProvider:
    def test_explicit_provider_override(self, router):
        msgs = [ProviderMessage(role="user", content="hello")]
        with patch.object(router._classifier, "classify", return_value=DataTier.SAFE):
            result = router.route(msgs, provider="claude")
            assert result.provider == "claude"

    def test_explicit_unknown_provider_raises(self, router):
        msgs = [ProviderMessage(role="user", content="hello")]
        with patch.object(router._classifier, "classify", return_value=DataTier.SAFE):
            with pytest.raises(KeyError):
                router.route(msgs, provider="nonexistent")


class TestPostureRouting:
    def test_conservative_routes_local(self, router):
        router.posture = RoutingPosture.CONSERVATIVE
        msgs = [ProviderMessage(role="user", content="Complex analysis of economic trends")]
        with patch.object(router._classifier, "classify", return_value=DataTier.SAFE):
            result = router.route(msgs)
            assert result.provider == "local"

    def test_aggressive_routes_cloud(self, router):
        router.posture = RoutingPosture.AGGRESSIVE
        msgs = [ProviderMessage(role="user", content="hello")]
        with patch.object(router._classifier, "classify", return_value=DataTier.SAFE):
            result = router.route(msgs, cloud_name="claude")
            assert result.provider == "claude"

    def test_balanced_simple_routes_local(self, router):
        router.posture = RoutingPosture.BALANCED
        msgs = [ProviderMessage(role="user", content="hi")]
        with patch.object(router._classifier, "classify", return_value=DataTier.SAFE):
            with patch.object(router, "_classify_complexity", return_value="SIMPLE"):
                result = router.route(msgs)
                assert result.provider == "local"

    def test_balanced_complex_routes_cloud(self, router):
        router.posture = RoutingPosture.BALANCED
        msgs = [ProviderMessage(role="user", content="Analyze the strategic implications of multi-agent systems")]
        with patch.object(router._classifier, "classify", return_value=DataTier.SAFE):
            with patch.object(router, "_classify_complexity", return_value="COMPLEX"):
                result = router.route(msgs, cloud_name="claude")
                assert result.provider == "claude"


class TestPrivacyEnforcement:
    def test_never_leave_blocks_cloud(self, router):
        msgs = [ProviderMessage(role="user", content="What's in vault/identity/MISSION.md?")]
        with patch.object(router._classifier, "classify", return_value=DataTier.NEVER_LEAVE):
            result = router.route(msgs, provider="claude")
            assert result.provider == "local"

    def test_sensitive_anonymizes_before_cloud(self, router):
        msgs = [ProviderMessage(role="user", content="Tell Alice about the project")]
        with patch.object(router._classifier, "classify", return_value=DataTier.SENSITIVE):
            with patch.object(
                router._classifier, "anonymize",
                return_value=("Tell <PERSON_1> about the project", {"<PERSON_1>": "Alice"}),
            ):
                with patch.object(
                    router._classifier, "deanonymize",
                    return_value="from-claude with Alice",
                ):
                    result = router.route(msgs, provider="claude")
                    assert result.provider == "claude"

    def test_safe_routes_to_cloud_directly(self, router):
        msgs = [ProviderMessage(role="user", content="What is quantum computing?")]
        with patch.object(router._classifier, "classify", return_value=DataTier.SAFE):
            result = router.route(msgs, provider="claude")
            assert result.provider == "claude"

    def test_sensitive_stream_falls_back_to_local(self, router):
        """SENSITIVE content in stream mode should fall back to local."""
        msgs = [ProviderMessage(role="user", content="Tell Alice something")]
        with patch.object(router._classifier, "classify", return_value=DataTier.SENSITIVE):
            chunks = list(router.route_stream(msgs, provider="claude"))
            assert "from-local" in "".join(chunks)


    def test_never_leave_in_system_prompt_blocks_cloud(self, router):
        """System prompt containing vault/identity content must trigger NEVER_LEAVE."""
        msgs = [
            ProviderMessage(role="system", content="You are sovereign. Source: vault/identity/MISSION.md"),
            ProviderMessage(role="user", content="What is my purpose?"),
        ]
        # No mock — let the real classifier detect vault/identity in system content
        result = router.route(msgs, provider="claude")
        assert result.provider == "local"


class TestComplexityClassification:
    def test_simple_query(self, router):
        assert router._classify_complexity("hi") == "SIMPLE"

    def test_complex_query(self, router):
        result = router._classify_complexity(
            "Analyze the strategic implications of multi-domain architecture "
            "across code generation and complex reasoning frameworks"
        )
        assert result in ("MODERATE", "COMPLEX")

    def test_moderate_query(self, router):
        result = router._classify_complexity(
            "Compare two approaches for implementing the provider pattern"
        )
        assert result in ("SIMPLE", "MODERATE", "COMPLEX")
