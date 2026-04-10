"""Tests for PrivacyAwareRouter — posture-based provider routing with privacy enforcement."""

from unittest.mock import MagicMock, patch

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


    def test_system_prompt_identity_does_not_block_safe_user_query(self, router):
        """System prompt with vault/identity refs should NOT block a safe user query.

        T-083: classifier uses scope='user_input' for routing — only user messages
        are classified. System prompt identity is filtered by _filter_cloud_context
        as the second defense layer.
        """
        msgs = [
            ProviderMessage(role="system", content="You are sovereign. Source: vault/identity/MISSION.md"),
            ProviderMessage(role="user", content="What is my purpose?"),
        ]
        pii_result = MagicMock(has_pii=False, entities=[])
        with patch("core.safety.pii.detect_pii", return_value=pii_result):
            result = router.route(msgs, provider="claude")
        assert result.provider == "claude"

    def test_never_leave_user_query_blocks_cloud(self, router):
        """User query with NEVER_LEAVE pattern still blocks cloud routing."""
        msgs = [
            ProviderMessage(role="system", content="General assistant."),
            ProviderMessage(role="user", content="Show me vault/identity/TELOS_01.md"),
        ]
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


class _UnavailableProvider(_FakeProvider):
    """Provider that reports itself as unavailable (e.g. Ollama stopped)."""
    def is_available(self):
        return False


class TestAvailabilityFallback:
    """T-120b: Router promotes to cloud when local provider is unavailable."""

    def test_local_unavailable_promotes_to_cloud(self):
        reg = ProviderRegistry()
        reg.register("local", _UnavailableProvider("local"))
        reg.register("gemini", _FakeProvider("gemini"))
        router = PrivacyAwareRouter(registry=reg, local_name="local")

        msgs = [ProviderMessage(role="user", content="hello")]
        with patch.object(router._classifier, "classify", return_value=DataTier.SAFE):
            result = router.route(msgs)
        assert result.provider == "gemini"

    def test_local_unavailable_no_cloud_stays_local(self):
        """When local is down and no cloud exists, returns local (will error at generate)."""
        reg = ProviderRegistry()
        reg.register("local", _UnavailableProvider("local"))
        router = PrivacyAwareRouter(registry=reg, local_name="local")

        resolved = router._resolve_provider(None, None, "hello", DataTier.SAFE)
        assert resolved == "local"

    def test_local_available_stays_local(self, router):
        """When local is up, standard resolution stays local."""
        resolved = router._resolve_provider(None, None, "hello", DataTier.SAFE)
        assert resolved == "local"

    def test_explicit_unavailable_promotes_to_cloud(self):
        """Even explicit provider promotes to cloud if unavailable."""
        reg = ProviderRegistry()
        reg.register("local", _UnavailableProvider("local"))
        reg.register("gemini", _FakeProvider("gemini"))
        router = PrivacyAwareRouter(registry=reg, local_name="local")

        resolved = router._resolve_provider("local", None, "hello", DataTier.SAFE)
        assert resolved == "gemini"

    def test_conservative_unavailable_promotes(self):
        """CONSERVATIVE posture still promotes if local is down."""
        reg = ProviderRegistry()
        reg.register("local", _UnavailableProvider("local"))
        reg.register("gemini", _FakeProvider("gemini"))
        router = PrivacyAwareRouter(
            registry=reg, local_name="local", posture=RoutingPosture.CONSERVATIVE,
        )

        resolved = router._resolve_provider(None, None, "hello", DataTier.SAFE)
        assert resolved == "gemini"
