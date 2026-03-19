"""Tests for Room management REST API endpoints."""
from __future__ import annotations

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


class TestRoomsAPI:
    def test_list_rooms(self, client):
        resp = client.get("/api/rooms")
        assert resp.status_code == 200
        rooms = resp.json()
        assert any(r["id"] == "home" for r in rooms)

    def test_get_active_room(self, client):
        resp = client.get("/api/rooms/active")
        assert resp.status_code == 200
        assert resp.json()["id"] == "home"

    def test_get_room_by_id(self, client):
        resp = client.get("/api/rooms/home")
        assert resp.status_code == 200
        assert resp.json()["name"] == "Home"

    def test_get_room_not_found(self, client):
        resp = client.get("/api/rooms/nonexistent")
        assert resp.status_code == 404

    def test_create_room(self, client):
        resp = client.post("/api/rooms", json={
            "id": "test", "name": "Test Room",
        })
        assert resp.status_code == 200
        assert resp.json()["id"] == "test"

    def test_create_room_with_template(self, client):
        resp = client.post("/api/rooms", json={
            "id": "myresearch", "name": "My Research", "template": "researcher",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["vault_scope"]["mode"] == "all"

    def test_create_duplicate_fails(self, client):
        client.post("/api/rooms", json={"id": "dup", "name": "Dup"})
        resp = client.post("/api/rooms", json={"id": "dup", "name": "Dup2"})
        assert resp.status_code == 400

    def test_update_room(self, client):
        client.post("/api/rooms", json={"id": "edit-me", "name": "Edit Me"})
        resp = client.put("/api/rooms/edit-me", json={"name": "Edited"})
        assert resp.status_code == 200
        assert resp.json()["name"] == "Edited"

    def test_delete_room(self, client):
        client.post("/api/rooms", json={"id": "delete-me", "name": "Delete Me"})
        resp = client.delete("/api/rooms/delete-me")
        assert resp.status_code == 200

    def test_delete_home_fails(self, client):
        resp = client.delete("/api/rooms/home")
        assert resp.status_code == 400

    def test_switch_room(self, client):
        client.post("/api/rooms", json={"id": "switch-to", "name": "Switch To"})
        resp = client.post("/api/rooms/switch", json={"room_id": "switch-to"})
        assert resp.status_code == 200
        assert resp.json()["id"] == "switch-to"
        active = client.get("/api/rooms/active").json()
        assert active["id"] == "switch-to"

    def test_state_includes_active_room(self, client):
        resp = client.get("/api/state")
        assert resp.status_code == 200
        assert "active_room" in resp.json()

    def test_chat_request_model_field(self):
        from core.interface.api.routes.chat import ChatRequest
        req = ChatRequest(query="test", model="qwen2.5:7b")
        assert req.model == "qwen2.5:7b"
