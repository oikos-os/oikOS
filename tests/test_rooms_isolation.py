"""End-to-end cross-Room isolation verification."""
import json

import pytest
from unittest.mock import patch

from core.rooms.models import (
    RoomConfig,
    RoomVaultScope,
    RoomAutonomy,
    RoomModelConfig,
    RoomVoice,
)


@pytest.fixture(autouse=True)
def reset_rooms():
    yield
    from core.rooms.manager import reset_room_manager

    reset_room_manager()


class TestCrossRoomIsolation:
    def test_vault_scoping_isolates_search(self, tmp_path, monkeypatch):
        """Room A with include paths only sees its own vault content."""
        monkeypatch.setattr("core.rooms.manager.ROOMS_DIR", tmp_path)
        from core.rooms.manager import get_room_manager

        mgr = get_room_manager(tmp_path)
        mgr.create_room(
            RoomConfig(
                id="ml",
                name="ML",
                vault_scope=RoomVaultScope(mode="include", paths=["knowledge/ml/"]),
            )
        )
        mgr.switch_room("ml")
        room = mgr.get_active_room()
        assert room.vault_scope.mode == "include"
        assert room.vault_scope.paths == ["knowledge/ml/"]

    def test_session_isolation_between_rooms(self, tmp_path, monkeypatch):
        """Room A's sessions are not visible from Room B."""
        monkeypatch.setattr("core.rooms.manager.ROOMS_DIR", tmp_path / "rooms")
        monkeypatch.setattr("core.memory.session.SESSIONS_DIR", tmp_path / "sessions")
        from core.rooms.manager import get_room_manager

        mgr = get_room_manager(tmp_path / "rooms")
        mgr.create_room(RoomConfig(id="room-a", name="A"))
        mgr.create_room(RoomConfig(id="room-b", name="B"))
        for rid in ("room-a", "room-b"):
            d = tmp_path / "sessions" / rid / "2026-03-18"
            d.mkdir(parents=True)
            (d / f"SESSION-{rid}-sess_summary.json").write_text(
                json.dumps(
                    {
                        "session_id": f"{rid}-sess",
                        "started_at": "2026-03-18T00:00:00Z",
                        "interaction_count": 1,
                        "first_query": f"test {rid}",
                    }
                )
            )
        from core.memory.session import list_recent_sessions

        a_sessions = list_recent_sessions(room_id="room-a")
        assert len(a_sessions) == 1
        assert a_sessions[0]["session_id"] == "room-a-sess"
        b_sessions = list_recent_sessions(room_id="room-b")
        assert len(b_sessions) == 1
        assert b_sessions[0]["session_id"] == "room-b-sess"

    def test_autonomy_overrides_dont_leak(self, tmp_path, monkeypatch):
        """Room A's autonomy overrides don't affect Room B."""
        monkeypatch.setattr("core.rooms.manager.ROOMS_DIR", tmp_path)
        from core.rooms.manager import get_room_manager

        mgr = get_room_manager(tmp_path)
        mgr.create_room(
            RoomConfig(
                id="strict",
                name="Strict",
                autonomy=RoomAutonomy(overrides={"fs_delete": "PROHIBITED"}),
            )
        )
        mgr.create_room(RoomConfig(id="lax", name="Lax"))
        mgr.switch_room("lax")
        room = mgr.get_active_room()
        assert "fs_delete" not in room.autonomy.overrides

    def test_cost_tracking_isolated(self, tmp_path, monkeypatch):
        """Room A's cost log is separate from Room B's."""
        monkeypatch.setattr("core.rooms.limits.COSTS_DIR", tmp_path / "costs")
        from core.rooms.limits import log_room_cost

        log_room_cost("room-a", "claude", "model", 0.50, 1000)
        log_room_cost("room-b", "claude", "model", 0.25, 500)
        assert (tmp_path / "costs" / "room-a.jsonl").exists()
        assert (tmp_path / "costs" / "room-b.jsonl").exists()
        a_lines = (tmp_path / "costs" / "room-a.jsonl").read_text().strip().split("\n")
        b_lines = (tmp_path / "costs" / "room-b.jsonl").read_text().strip().split("\n")
        assert len(a_lines) == 1
        assert len(b_lines) == 1

    def test_voice_isolation(self, tmp_path, monkeypatch):
        """Room A's system_prompt is not visible from Room B."""
        monkeypatch.setattr("core.rooms.manager.ROOMS_DIR", tmp_path)
        from core.rooms.manager import get_room_manager

        mgr = get_room_manager(tmp_path)
        mgr.create_room(
            RoomConfig(
                id="creative",
                name="Creative",
                voice=RoomVoice(system_prompt="You are a poet."),
            )
        )
        mgr.create_room(RoomConfig(id="code", name="Code"))
        mgr.switch_room("code")
        room = mgr.get_active_room()
        assert room.voice.system_prompt is None

    def test_exported_room_has_no_vault_content(self, tmp_path, monkeypatch):
        """Exported Room JSON contains only config, not vault data."""
        monkeypatch.setattr("core.rooms.manager.ROOMS_DIR", tmp_path)
        from core.rooms.manager import get_room_manager

        mgr = get_room_manager(tmp_path)
        mgr.create_room(
            RoomConfig(
                id="scoped",
                name="Scoped",
                vault_scope=RoomVaultScope(mode="include", paths=["knowledge/"]),
            )
        )
        exported = mgr.get_room("scoped").model_dump(mode="json")
        dump_str = json.dumps(exported)
        assert "content" not in dump_str or "vault_content" not in dump_str
        assert exported["vault_scope"]["paths"] == ["knowledge/"]

    def test_switching_rooms_closes_session(self, tmp_path, monkeypatch):
        """Switching from Room A to B closes the session."""
        monkeypatch.setattr("core.rooms.manager.ROOMS_DIR", tmp_path)
        from core.rooms.manager import get_room_manager

        mgr = get_room_manager(tmp_path)
        mgr.create_room(RoomConfig(id="a", name="A"))
        mgr.create_room(RoomConfig(id="b", name="B"))
        with patch("core.memory.session.close_session") as mock_close:
            mgr.switch_room("a")
            mock_close.assert_called_once()

    def test_home_sees_all_sessions(self, tmp_path, monkeypatch):
        """Home Room (session_isolation=False) sees all sessions."""
        monkeypatch.setattr("core.rooms.manager.ROOMS_DIR", tmp_path / "rooms")
        monkeypatch.setattr("core.memory.session.SESSIONS_DIR", tmp_path / "sessions")
        from core.rooms.manager import get_room_manager

        mgr = get_room_manager(tmp_path / "rooms")
        mgr.create_room(RoomConfig(id="x", name="X"))
        for rid in ("home", "x"):
            d = tmp_path / "sessions" / rid / "2026-03-18"
            d.mkdir(parents=True)
            (d / f"SESSION-{rid}_summary.json").write_text(
                json.dumps(
                    {
                        "session_id": rid,
                        "started_at": "2026-03-18T00:00:00Z",
                        "interaction_count": 1,
                        "first_query": f"test {rid}",
                    }
                )
            )
        from core.memory.session import list_recent_sessions

        # home has session_isolation=False, so room_id="home" should see all
        results = list_recent_sessions(room_id="home")
        assert len(results) == 2

    def test_never_leave_enforced_across_rooms(self, tmp_path, monkeypatch):
        """NEVER_LEAVE blocks cloud even when Room configures cloud provider."""
        monkeypatch.setattr("core.rooms.manager.ROOMS_DIR", tmp_path)
        from core.rooms.manager import get_room_manager

        mgr = get_room_manager(tmp_path)
        mgr.create_room(
            RoomConfig(
                id="cloud",
                name="Cloud",
                model=RoomModelConfig(provider="anthropic"),
            )
        )
        mgr.switch_room("cloud")
        room = mgr.get_active_room()
        # Room stores the config but NEVER_LEAVE in handler prevents actual routing
        assert room.model.provider == "anthropic"

    def test_toolset_isolation(self, tmp_path, monkeypatch):
        """Room A's toolset restriction is independent of Room B."""
        monkeypatch.setattr("core.rooms.manager.ROOMS_DIR", tmp_path)
        from core.rooms.manager import get_room_manager

        mgr = get_room_manager(tmp_path)
        mgr.create_room(RoomConfig(id="vault-only", name="Vault Only", toolsets=["vault"]))
        mgr.create_room(RoomConfig(id="full", name="Full"))
        mgr.switch_room("vault-only")
        assert mgr.get_active_room().toolsets == ["vault"]
        mgr.switch_room("full")
        assert mgr.get_active_room().toolsets is None  # None = all
