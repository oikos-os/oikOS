"""Integration tests — handler uses ProviderRegistry for inference routing."""

from unittest.mock import MagicMock, patch

import pytest

from core.cognition.providers.bootstrap import create_registry
from core.cognition.providers.registry import ProviderRegistry
from core.cognition.providers.router import PrivacyAwareRouter
from core.interface.models import (
    CompletionResponse,
    DataTier,
    ProviderMessage,
    RoutingPosture,
)


class TestRegistryBootstrap:
    def test_registry_with_all_keys(self):
        with patch.dict("os.environ", {
            "ANTHROPIC_API_KEY": "test",
            "GEMINI_API_KEY": "test",
        }):
            reg = create_registry()
            assert "local" in reg.list_all()
            assert "claude" in reg.list_all()
            assert "gemini" in reg.list_all()

    def test_registry_local_only(self):
        with patch.dict("os.environ", {}, clear=False):
            import os
            os.environ.pop("ANTHROPIC_API_KEY", None)
            os.environ.pop("GEMINI_API_KEY", None)
            reg = create_registry()
            assert reg.list_all() == ["local"]


class TestRouterEndToEnd:
    def test_conservative_posture_forces_local(self):
        reg = ProviderRegistry()
        local = MagicMock()
        local.provider_name = "ollama"
        local.is_available.return_value = True
        local.generate.return_value = CompletionResponse(
            text="local response", model="qwen2.5:14b", provider="ollama"
        )
        cloud = MagicMock()
        cloud.provider_name = "anthropic"
        cloud.is_available.return_value = True

        reg.register("local", local)
        reg.register("claude", cloud)

        router = PrivacyAwareRouter(reg, posture=RoutingPosture.CONSERVATIVE)
        with patch.object(router._classifier, "classify", return_value=DataTier.SAFE):
            msgs = [ProviderMessage(role="user", content="complex analysis")]
            result = router.route(msgs)

        assert result.text == "local response"
        local.generate.assert_called_once()
        cloud.generate.assert_not_called()

    def test_never_leave_overrides_explicit_provider(self):
        reg = ProviderRegistry()
        local = MagicMock()
        local.provider_name = "ollama"
        local.is_available.return_value = True
        local.generate.return_value = CompletionResponse(
            text="local response", model="qwen2.5:14b", provider="ollama"
        )
        cloud = MagicMock()
        cloud.provider_name = "anthropic"
        cloud.is_available.return_value = True

        reg.register("local", local)
        reg.register("claude", cloud)

        router = PrivacyAwareRouter(reg)
        with patch.object(router._classifier, "classify", return_value=DataTier.NEVER_LEAVE):
            msgs = [ProviderMessage(role="user", content="vault/identity/MISSION.md")]
            result = router.route(msgs, provider="claude")

        assert result.text == "local response"
        local.generate.assert_called_once()
        cloud.generate.assert_not_called()

    def test_sensitive_content_anonymized(self):
        reg = ProviderRegistry()
        local = MagicMock()
        local.provider_name = "ollama"
        local.is_available.return_value = True
        cloud = MagicMock()
        cloud.provider_name = "anthropic"
        cloud.is_available.return_value = True
        cloud.generate.return_value = CompletionResponse(
            text="Hello <PERSON_1>!", model="claude", provider="anthropic"
        )

        reg.register("local", local)
        reg.register("claude", cloud)

        router = PrivacyAwareRouter(reg)
        with patch.object(router._classifier, "classify", return_value=DataTier.SENSITIVE):
            with patch.object(
                router._classifier, "anonymize",
                return_value=("Tell <PERSON_1> something", {"<PERSON_1>": "Alice"}),
            ):
                with patch.object(
                    router._classifier, "deanonymize",
                    return_value="Hello Alice!",
                ):
                    msgs = [ProviderMessage(role="user", content="Tell Alice something")]
                    result = router.route(msgs, provider="claude")

        assert result.text == "Hello Alice!"
        assert result.provider == "anthropic"

    def test_fallback_chain_on_provider_set(self):
        """If explicit provider is set, use it directly (no fallback in route)."""
        reg = ProviderRegistry()
        local = MagicMock()
        local.provider_name = "ollama"
        local.is_available.return_value = True
        local.generate.return_value = CompletionResponse(
            text="local ok", model="qwen", provider="ollama"
        )
        reg.register("local", local)

        router = PrivacyAwareRouter(reg, posture=RoutingPosture.BALANCED)
        with patch.object(router._classifier, "classify", return_value=DataTier.SAFE):
            msgs = [ProviderMessage(role="user", content="hi")]
            result = router.route(msgs)

        assert result.provider == "ollama"


class TestProviderSwitching:
    def test_set_default_switches_provider(self):
        reg = ProviderRegistry()
        p1 = MagicMock()
        p1.provider_name = "ollama"
        p1.is_available.return_value = True
        p2 = MagicMock()
        p2.provider_name = "anthropic"
        p2.is_available.return_value = True

        reg.register("local", p1)
        reg.register("claude", p2)

        assert reg.get_default().provider_name == "ollama"
        reg.set_default("claude")
        assert reg.get_default().provider_name == "anthropic"


class TestHandlerProviderDispatch:
    def test_get_provider_registry_returns_registry(self):
        from core.cognition.handler import get_provider_registry
        with patch("core.cognition.providers.bootstrap.create_registry") as mock_create:
            mock_create.return_value = ProviderRegistry()
            # Force re-init
            import core.cognition.handler as h
            h._provider_registry = None
            reg = h.get_provider_registry()
            assert isinstance(reg, ProviderRegistry)
            h._provider_registry = None  # cleanup

    def test_get_provider_router_returns_router(self):
        from core.cognition.handler import get_provider_router
        with patch("core.cognition.providers.bootstrap.create_registry") as mock_create:
            mock_reg = ProviderRegistry()
            mock_create.return_value = mock_reg
            import core.cognition.handler as h
            h._provider_registry = None
            h._provider_router = None
            router = h.get_provider_router()
            assert isinstance(router, PrivacyAwareRouter)
            h._provider_registry = None
            h._provider_router = None  # cleanup
