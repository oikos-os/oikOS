"""Tests for T-084: Per-Room provider access control (allowed_providers)."""

from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError


class TestRoomModelAllowedProviders:
    """Schema-level tests for the allowed_providers field."""

    def test_null_means_all_providers(self):
        from core.rooms.models import RoomConfig
        room = RoomConfig(id="test", name="Test")
        assert room.allowed_providers is None

    def test_missing_key_treated_as_null(self):
        from core.rooms.models import RoomConfig
        data = {"id": "test", "name": "Test"}
        room = RoomConfig.model_validate(data)
        assert room.allowed_providers is None

    def test_explicit_list_preserved(self):
        from core.rooms.models import RoomConfig
        room = RoomConfig(id="test", name="Test", allowed_providers=["local", "gemini"])
        assert room.allowed_providers == ["local", "gemini"]

    def test_empty_list_rejected(self):
        from core.rooms.models import RoomConfig
        with pytest.raises(ValidationError, match="cannot be empty"):
            RoomConfig(id="test", name="Test", allowed_providers=[])

    def test_single_provider_allowed(self):
        from core.rooms.models import RoomConfig
        room = RoomConfig(id="test", name="Test", allowed_providers=["local"])
        assert room.allowed_providers == ["local"]

    def test_serialization_roundtrip(self):
        from core.rooms.models import RoomConfig
        room = RoomConfig(id="test", name="Test", allowed_providers=["local", "anthropic-oauth"])
        data = room.model_dump()
        assert data["allowed_providers"] == ["local", "anthropic-oauth"]
        restored = RoomConfig.model_validate(data)
        assert restored.allowed_providers == ["local", "anthropic-oauth"]


class TestRouterProviderEnforcement:
    """Router-level enforcement of allowed_providers."""

    def _make_router(self):
        from core.cognition.providers.registry import ProviderRegistry
        from core.cognition.providers.router import PrivacyAwareRouter
        from core.interface.models import RoutingPosture

        reg = ProviderRegistry()
        mock_local = MagicMock()
        mock_local.is_available.return_value = True
        mock_local.generate.return_value = MagicMock(text="local answer", provider="local", model="qwen", input_tokens=0, output_tokens=0, latency_ms=0, logprobs=None, raw=None)
        mock_local.stream.return_value = iter(["local stream"])

        mock_gemini = MagicMock()
        mock_gemini.is_available.return_value = True
        mock_gemini.generate.return_value = MagicMock(text="gemini answer", provider="gemini", model="gemini-2.5-pro", input_tokens=0, output_tokens=0, latency_ms=0, logprobs=None, raw=None)
        mock_gemini.stream.return_value = iter(["gemini stream"])

        mock_oauth = MagicMock()
        mock_oauth.is_available.return_value = True
        mock_oauth.generate.return_value = MagicMock(text="opus answer", provider="anthropic-oauth", model="claude-opus-4-6", input_tokens=0, output_tokens=0, latency_ms=0, logprobs=None, raw=None)
        mock_oauth.stream.return_value = iter(["opus stream"])

        reg.register("local", mock_local)
        reg.register("gemini", mock_gemini)
        reg.register("anthropic-oauth", mock_oauth)

        router = PrivacyAwareRouter(reg, local_name="local", posture=RoutingPosture.BALANCED)
        return router

    def _msgs(self, text="hello"):
        from core.interface.models import ProviderMessage
        return [ProviderMessage(role="user", content=text)]

    def test_null_allowed_permits_all(self):
        router = self._make_router()
        result = router.route(self._msgs(), provider="gemini", allowed_providers=None)
        assert result.text == "gemini answer"

    def test_allowed_provider_passes(self):
        router = self._make_router()
        result = router.route(self._msgs(), provider="gemini", allowed_providers=["local", "gemini"])
        assert result.text == "gemini answer"

    def test_disallowed_provider_falls_back_to_local(self):
        router = self._make_router()
        result = router.route(self._msgs(), provider="anthropic-oauth", allowed_providers=["local", "gemini"])
        assert result.text == "local answer"

    def test_local_only_blocks_all_cloud(self):
        router = self._make_router()
        result = router.route(self._msgs(), provider="gemini", allowed_providers=["local"])
        assert result.text == "local answer"

    def test_stream_allowed_provider_passes(self):
        router = self._make_router()
        chunks = list(router.route_stream(self._msgs(), provider="anthropic-oauth", allowed_providers=["local", "anthropic-oauth"]))
        assert chunks == ["opus stream"]

    def test_stream_disallowed_falls_back(self):
        router = self._make_router()
        chunks = list(router.route_stream(self._msgs(), provider="anthropic-oauth", allowed_providers=["local"]))
        assert chunks == ["local stream"]

    def test_auto_mode_skips_disallowed_cloud(self):
        """When no explicit provider, auto mode should not route to a disallowed cloud provider."""
        router = self._make_router()
        # BALANCED posture with complex query would normally route to cloud
        complex_query = "Analyze the strategic architectural framework for implementing multi-step debugging with refactoring"
        result = router.route(self._msgs(complex_query), allowed_providers=["local"])
        assert result.text == "local answer"


class TestProvidersAPIEndpoint:
    """Tests for PUT /api/rooms/{id}/providers endpoint."""

    @patch("core.rooms.manager.get_room_manager")
    @patch("core.cognition.providers.bootstrap.create_registry")
    def test_set_providers_success(self, mock_registry, mock_mgr):
        from core.interface.api.routes.rooms import set_room_providers, RoomProvidersRequest

        mock_reg = MagicMock()
        mock_reg.list_all.return_value = ["local", "gemini", "anthropic-oauth"]
        mock_registry.return_value = mock_reg

        mock_room = MagicMock()
        mock_room.model_dump.return_value = {"id": "home", "allowed_providers": ["local", "gemini"]}
        mock_mgr.return_value.update_room.return_value = mock_room

        result = set_room_providers("home", RoomProvidersRequest(providers=["local", "gemini"]))
        assert result["allowed_providers"] == ["local", "gemini"]
        mock_mgr.return_value.update_room.assert_called_once_with("home", {"allowed_providers": ["local", "gemini"]})

    @patch("core.cognition.providers.bootstrap.create_registry")
    def test_set_providers_rejects_empty(self, mock_registry):
        from fastapi import HTTPException
        from core.interface.api.routes.rooms import set_room_providers, RoomProvidersRequest

        with pytest.raises(HTTPException) as exc:
            set_room_providers("home", RoomProvidersRequest(providers=[]))
        assert exc.value.status_code == 400

    @patch("core.cognition.providers.bootstrap.create_registry")
    def test_set_providers_rejects_unknown(self, mock_registry):
        from fastapi import HTTPException
        from core.interface.api.routes.rooms import set_room_providers, RoomProvidersRequest

        mock_reg = MagicMock()
        mock_reg.list_all.return_value = ["local", "gemini"]
        mock_registry.return_value = mock_reg

        with pytest.raises(HTTPException) as exc:
            set_room_providers("home", RoomProvidersRequest(providers=["local", "fake-provider"]))
        assert exc.value.status_code == 400
        assert "fake-provider" in str(exc.value.detail)
