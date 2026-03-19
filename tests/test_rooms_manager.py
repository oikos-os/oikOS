"""Tests for RoomManager CRUD, persistence, and active room."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from core.rooms.manager import RoomManager, get_room_manager, reset_room_manager
from core.rooms.models import RoomConfig


@pytest.fixture(autouse=True)
def reset_rooms():
    yield
    reset_room_manager()


@pytest.fixture
def mgr(tmp_path):
    return RoomManager(rooms_dir=tmp_path)


# ── list / get ────────────────────────────────────────────────────────


def test_list_rooms_contains_home(mgr):
    rooms = mgr.list_rooms()
    assert len(rooms) >= 1
    assert rooms[0].id == "home"


def test_get_home_room(mgr):
    home = mgr.get_room("home")
    assert home.id == "home"
    assert home.vault_scope.mode == "all"


def test_get_nonexistent_raises(mgr):
    with pytest.raises(ValueError, match="not found"):
        mgr.get_room("nonexistent")


def test_list_rooms_home_first(mgr):
    mgr.create_room(RoomConfig(id="alpha", name="Alpha"))
    mgr.create_room(RoomConfig(id="beta", name="Beta"))
    rooms = mgr.list_rooms()
    assert rooms[0].id == "home"


# ── create ────────────────────────────────────────────────────────────


def test_create_room_persists(tmp_path):
    mgr = RoomManager(rooms_dir=tmp_path)
    room = RoomConfig(id="test1", name="Test One", toolsets=["vault", "system"])
    mgr.create_room(room)
    assert (tmp_path / "test1.json").exists()
    data = json.loads((tmp_path / "test1.json").read_text(encoding="utf-8"))
    assert data["id"] == "test1"
    assert data["name"] == "Test One"


def test_create_room_duplicate_raises(mgr):
    mgr.create_room(RoomConfig(id="dup", name="Dup"))
    with pytest.raises(ValueError, match="already exists"):
        mgr.create_room(RoomConfig(id="dup", name="Dup Again"))


def test_create_room_invalid_toolset_raises(mgr):
    with pytest.raises(ValueError, match="Invalid toolsets"):
        mgr.create_room(RoomConfig(id="bad", name="Bad", toolsets=["vault", "fake_tool"]))


def test_create_room_none_toolsets_ok(mgr):
    room = mgr.create_room(RoomConfig(id="all_tools", name="All Tools"))
    assert room.toolsets is None


# ── update ────────────────────────────────────────────────────────────


def test_update_room_modifies(mgr):
    mgr.create_room(RoomConfig(id="upd", name="Original"))
    updated = mgr.update_room("upd", {"name": "Updated"})
    assert updated.name == "Updated"
    reloaded = mgr.get_room("upd")
    assert reloaded.name == "Updated"


def test_update_room_persists(tmp_path):
    mgr = RoomManager(rooms_dir=tmp_path)
    mgr.create_room(RoomConfig(id="upd2", name="Before"))
    mgr.update_room("upd2", {"description": "Now described"})
    data = json.loads((tmp_path / "upd2.json").read_text(encoding="utf-8"))
    assert data["description"] == "Now described"


def test_update_room_sets_updated_at(mgr):
    mgr.create_room(RoomConfig(id="ts", name="Timestamps"))
    original = mgr.get_room("ts")
    updated = mgr.update_room("ts", {"name": "Timestamps v2"})
    assert updated.updated_at >= original.updated_at


# ── delete ────────────────────────────────────────────────────────────


def test_delete_home_raises(mgr):
    with pytest.raises(ValueError, match="Cannot delete"):
        mgr.delete_room("home")


def test_delete_room_removes_file(tmp_path):
    mgr = RoomManager(rooms_dir=tmp_path)
    mgr.create_room(RoomConfig(id="gone", name="Gone"))
    assert (tmp_path / "gone.json").exists()
    mgr.delete_room("gone")
    assert not (tmp_path / "gone.json").exists()
    with pytest.raises(ValueError, match="not found"):
        mgr.get_room("gone")


def test_delete_active_resets_to_home(tmp_path):
    mgr = RoomManager(rooms_dir=tmp_path)
    mgr.create_room(RoomConfig(id="temp", name="Temp"))
    with patch("core.memory.session.close_session"):
        mgr.switch_room("temp")
    mgr.delete_room("temp")
    assert mgr.get_active_room().id == "home"


def test_delete_nonexistent_raises(mgr):
    with pytest.raises(ValueError, match="not found"):
        mgr.delete_room("ghost")


# ── active room / switch ──────────────────────────────────────────────


def test_active_room_defaults_to_home(mgr):
    assert mgr.get_active_room().id == "home"


@patch("core.memory.session.close_session")
def test_switch_room(mock_close, mgr):
    mgr.create_room(RoomConfig(id="work", name="Work"))
    result = mgr.switch_room("work")
    assert result.id == "work"
    assert mgr.get_active_room().id == "work"
    mock_close.assert_called_once_with(reason="room_switch")


def test_switch_nonexistent_raises(mgr):
    with pytest.raises(ValueError, match="not found"):
        mgr.switch_room("nowhere")


@patch("core.memory.session.close_session")
def test_switch_back_to_home(mock_close, mgr):
    mgr.create_room(RoomConfig(id="away", name="Away"))
    mgr.switch_room("away")
    mgr.switch_room("home")
    assert mgr.get_active_room().id == "home"


# ── roundtrip ─────────────────────────────────────────────────────────


def test_json_roundtrip(tmp_path):
    mgr = RoomManager(rooms_dir=tmp_path)
    original = RoomConfig(
        id="round",
        name="Roundtrip",
        description="Test roundtrip",
        vault_scope={"mode": "include", "paths": ["knowledge"], "tags": ["test"]},
        toolsets=["vault", "system"],
        autonomy={"overrides": {"oikos_vault_ingest": "ASK_FIRST"}},
        model={"provider": "local", "model": "qwen2.5:7b"},
        voice={"system_prompt": "Be concise.", "temperature": 0.5},
    )
    mgr.create_room(original)
    # Reload from disk
    mgr2 = RoomManager(rooms_dir=tmp_path)
    loaded = mgr2.get_room("round")
    assert loaded.name == original.name
    assert loaded.vault_scope.mode == "include"
    assert loaded.vault_scope.paths == ["knowledge"]
    assert loaded.toolsets == ["vault", "system"]
    assert loaded.autonomy.overrides == {"oikos_vault_ingest": "ASK_FIRST"}
    assert loaded.model.provider == "local"
    assert loaded.voice.temperature == 0.5


# ── singleton ─────────────────────────────────────────────────────────


def test_get_room_manager_singleton(tmp_path):
    m1 = get_room_manager(rooms_dir=tmp_path)
    m2 = get_room_manager()
    assert m1 is m2


def test_reset_room_manager(tmp_path):
    m1 = get_room_manager(rooms_dir=tmp_path)
    reset_room_manager()
    m2 = get_room_manager(rooms_dir=tmp_path)
    assert m1 is not m2
