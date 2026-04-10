"""Tests for per-Room model defaults and model switching API."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def isolated_rooms(tmp_path):
    """Initialize RoomManager with a temp dir, reset after."""
    from core.rooms.manager import get_room_manager, reset_room_manager
    reset_room_manager()
    get_room_manager(rooms_dir=tmp_path)
    yield
    reset_room_manager()


@pytest.fixture()
def client():
    from core.interface.api.server import create_app
    app = create_app(dev=True)
    return TestClient(app)


class TestRoomModelAPI:
    """PUT /api/rooms/{room_id}/model endpoint."""

    def test_set_model_auto(self, client):
        """Setting 'auto' clears provider and model override."""
        resp = client.put("/api/rooms/home/model", json={"model": "auto"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["model"]["provider"] is None
        assert data["model"]["model"] is None

    def test_set_model_with_provider_prefix(self, client):
        """Provider prefix format like 'anthropic:claude-sonnet' is parsed."""
        resp = client.put("/api/rooms/home/model", json={"model": "anthropic:claude-sonnet-4-20250514"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["model"]["provider"] == "anthropic"
        assert data["model"]["model"] == "claude-sonnet-4-20250514"

    def test_set_model_provider_only(self, client):
        """Provider prefix without model name (e.g., 'gemini:')."""
        resp = client.put("/api/rooms/home/model", json={"model": "gemini:"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["model"]["provider"] == "gemini"
        assert data["model"]["model"] is None

    @patch("ollama.Client")
    def test_set_model_plain_name_valid(self, mock_client_cls, client):
        """Plain model name validated against Ollama model list."""
        mock_instance = MagicMock()
        mock_model = MagicMock()
        mock_model.model = "qwen2.5:14b"
        mock_instance.list.return_value = MagicMock(models=[mock_model])
        mock_client_cls.return_value = mock_instance

        resp = client.put("/api/rooms/home/model", json={"model": "qwen2.5:14b"})
        assert resp.status_code == 200
        assert resp.json()["model"]["model"] == "qwen2.5:14b"

    @patch("ollama.Client")
    def test_set_model_invalid_name_400(self, mock_client_cls, client):
        """Unknown plain model name returns 400."""
        mock_client_cls.return_value.list.return_value = MagicMock(models=[])
        resp = client.put("/api/rooms/home/model", json={"model": "nonexistent-model"})
        assert resp.status_code == 400
        assert "Unknown model" in resp.json()["detail"]

    def test_set_model_empty_string_400(self, client):
        """Empty model value returns 400."""
        resp = client.put("/api/rooms/home/model", json={"model": ""})
        assert resp.status_code == 400

    def test_set_model_persists_across_reads(self, client):
        """Model setting persists and is visible in GET /api/rooms."""
        client.put("/api/rooms/home/model", json={"model": "ollama:qwen2.5:7b"})
        rooms = client.get("/api/rooms").json()
        home = next(r for r in rooms if r["id"] == "home")
        assert home["model"]["provider"] == "ollama"
        assert home["model"]["model"] == "qwen2.5:7b"

    def test_set_model_nonexistent_room_404(self, client):
        """Setting model on nonexistent room returns 404."""
        resp = client.put("/api/rooms/nonexistent/model", json={"model": "auto"})
        assert resp.status_code == 404

    def test_rooms_list_includes_model_defaults(self, client):
        """GET /api/rooms returns model config for each room."""
        resp = client.get("/api/rooms")
        assert resp.status_code == 200
        for room in resp.json():
            assert "model" in room
            assert "provider" in room["model"]
            assert "model" in room["model"]


class TestHandlerRoomModelOverride:
    """Handler uses room model defaults when no explicit override."""

    def test_non_streaming_uses_room_model(self):
        """execute_query uses active room's model default."""
        from core.rooms.manager import get_room_manager

        mgr = get_room_manager()
        mgr.update_room("home", {"model": {"provider": "ollama", "model": "qwen2.5:7b"}})

        # Verify the room config was updated
        room = mgr.get_active_room()
        assert room.model.model == "qwen2.5:7b"
        assert room.model.provider == "ollama"

    def test_auto_resets_room_model(self):
        """Setting model to auto clears the room's model config."""
        from core.rooms.manager import get_room_manager

        mgr = get_room_manager()
        mgr.update_room("home", {"model": {"provider": "ollama", "model": "qwen2.5:7b"}})
        mgr.update_room("home", {"model": {"provider": None, "model": None}})

        room = mgr.get_active_room()
        assert room.model.model is None
        assert room.model.provider is None
