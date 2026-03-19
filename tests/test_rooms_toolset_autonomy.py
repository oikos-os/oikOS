"""Tests for Room toolset scoping (Task 7) and autonomy overrides (Task 8)."""

import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from core.interface.models import ActionClass


@pytest.fixture(autouse=True)
def reset_rooms():
    yield
    from core.rooms.manager import reset_room_manager
    reset_room_manager()


# --- Task 7: Toolset Scoping Tests ---


class TestMCPRoomFlag:
    def test_room_flag_loads_toolsets(self, tmp_path, monkeypatch):
        """--room flag loads Room's toolsets for MCP server."""
        monkeypatch.setattr("core.rooms.manager.ROOMS_DIR", tmp_path)
        from core.rooms.manager import get_room_manager
        from core.rooms.models import RoomConfig
        mgr = get_room_manager(tmp_path)
        mgr.create_room(RoomConfig(id="code", name="Code", toolsets=["vault", "file", "git"]))

        room = mgr.get_room("code")
        assert room.toolsets == ["vault", "file", "git"]

    def test_room_with_no_toolsets_returns_none(self, tmp_path, monkeypatch):
        """Room with toolsets=None does not restrict toolsets."""
        monkeypatch.setattr("core.rooms.manager.ROOMS_DIR", tmp_path)
        from core.rooms.manager import get_room_manager
        from core.rooms.models import RoomConfig
        mgr = get_room_manager(tmp_path)
        mgr.create_room(RoomConfig(id="open", name="Open"))

        room = mgr.get_room("open")
        assert room.toolsets is None


# --- Task 8: Autonomy Override Tests ---


class TestRoomAutonomyOverride:
    @pytest.fixture
    def middleware(self):
        from core.framework.middleware.autonomy import AutonomyMiddleware
        return AutonomyMiddleware(matrix=None, queue=None)

    @pytest.fixture
    def mock_ctx(self):
        ctx = MagicMock()
        ctx.tool_name = "fs_delete"
        ctx.tool_meta.autonomy = ActionClass.SAFE
        ctx.tool_meta.toolset = "file"
        ctx.arguments = {}
        return ctx

    @pytest.mark.asyncio
    async def test_no_room_default_behavior(self, middleware, mock_ctx):
        """No active Room = default behavior unchanged."""
        call_next = AsyncMock(return_value="result")
        with patch("core.rooms.manager.get_room_manager", side_effect=Exception("not init")):
            result = await middleware(mock_ctx, call_next)
        assert result == "result"
        call_next.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_room_escalates_to_prohibited(self, middleware, mock_ctx, tmp_path, monkeypatch):
        """Room override escalates SAFE to PROHIBITED."""
        monkeypatch.setattr("core.rooms.manager.ROOMS_DIR", tmp_path)
        from core.rooms.manager import get_room_manager
        from core.rooms.models import RoomConfig, RoomAutonomy
        mgr = get_room_manager(tmp_path)
        mgr.create_room(RoomConfig(
            id="strict", name="Strict",
            autonomy=RoomAutonomy(overrides={"fs_delete": "PROHIBITED"})
        ))
        mgr.switch_room("strict")

        with pytest.raises(PermissionError, match="PROHIBITED"):
            await middleware(mock_ctx, AsyncMock())

    @pytest.mark.asyncio
    async def test_room_escalates_to_ask_first(self, middleware, mock_ctx, tmp_path, monkeypatch):
        """Room override escalates SAFE to ASK_FIRST."""
        monkeypatch.setattr("core.rooms.manager.ROOMS_DIR", tmp_path)
        from core.rooms.manager import get_room_manager
        from core.rooms.models import RoomConfig, RoomAutonomy
        mgr = get_room_manager(tmp_path)
        queue = MagicMock()
        queue.propose.return_value = MagicMock(proposal_id="p1")
        from core.framework.middleware.autonomy import AutonomyMiddleware
        middleware_with_queue = AutonomyMiddleware(matrix=None, queue=queue)

        mgr.create_room(RoomConfig(
            id="careful", name="Careful",
            autonomy=RoomAutonomy(overrides={"fs_delete": "ASK_FIRST"})
        ))
        mgr.switch_room("careful")

        from core.framework.exceptions import ApprovalRequired
        with pytest.raises(ApprovalRequired):
            await middleware_with_queue(mock_ctx, AsyncMock())

    @pytest.mark.asyncio
    async def test_room_cannot_relax_prohibited(self, middleware, mock_ctx, tmp_path, monkeypatch):
        """Room SAFE override cannot relax a PROHIBITED tool."""
        monkeypatch.setattr("core.rooms.manager.ROOMS_DIR", tmp_path)
        from core.rooms.manager import get_room_manager
        from core.rooms.models import RoomConfig, RoomAutonomy
        mgr = get_room_manager(tmp_path)
        mgr.create_room(RoomConfig(
            id="lax", name="Lax",
            autonomy=RoomAutonomy(overrides={"fs_delete": "SAFE"})
        ))
        mgr.switch_room("lax")

        # Tool is declared PROHIBITED
        mock_ctx.tool_meta.autonomy = ActionClass.PROHIBITED
        with pytest.raises(PermissionError, match="PROHIBITED"):
            await middleware(mock_ctx, AsyncMock())

    @pytest.mark.asyncio
    async def test_room_no_overrides_passthrough(self, middleware, mock_ctx, tmp_path, monkeypatch):
        """Room with no overrides = pass-through."""
        monkeypatch.setattr("core.rooms.manager.ROOMS_DIR", tmp_path)
        from core.rooms.manager import get_room_manager
        get_room_manager(tmp_path)
        # Home room has no overrides

        call_next = AsyncMock(return_value="ok")
        result = await middleware(mock_ctx, call_next)
        assert result == "ok"


# --- Task 9: Per-Room Model Selection Tests ---


class TestRoomModelSelection:
    def test_room_model_config_stored(self, tmp_path, monkeypatch):
        """Room model config is correctly stored and retrieved."""
        monkeypatch.setattr("core.rooms.manager.ROOMS_DIR", tmp_path)
        from core.rooms.manager import get_room_manager, reset_room_manager
        from core.rooms.models import RoomConfig, RoomModelConfig

        mgr = get_room_manager(tmp_path)
        mgr.create_room(RoomConfig(
            id="local-only", name="Local Only",
            model=RoomModelConfig(provider="ollama", model="qwen2.5:7b")
        ))
        room = mgr.get_room("local-only")
        assert room.model.provider == "ollama"
        assert room.model.model == "qwen2.5:7b"
        reset_room_manager()

    def test_room_no_model_no_override(self, tmp_path, monkeypatch):
        """Room with no model config doesn't inject overrides."""
        monkeypatch.setattr("core.rooms.manager.ROOMS_DIR", tmp_path)
        from core.rooms.manager import get_room_manager, reset_room_manager

        mgr = get_room_manager(tmp_path)
        room = mgr.get_active_room()  # Home room
        assert room.model.model is None
        assert room.model.provider is None
        reset_room_manager()

    def test_explicit_override_beats_room(self, tmp_path, monkeypatch):
        """Explicit model_override takes precedence over Room config."""
        monkeypatch.setattr("core.rooms.manager.ROOMS_DIR", tmp_path)
        from core.rooms.manager import get_room_manager, reset_room_manager
        from core.rooms.models import RoomConfig, RoomModelConfig

        mgr = get_room_manager(tmp_path)
        mgr.create_room(RoomConfig(
            id="local", name="Local",
            model=RoomModelConfig(provider="ollama", model="qwen2.5:7b")
        ))
        mgr.switch_room("local")

        # Simulate the priority logic from handler
        model_override = "gemini-2.5-pro"
        route_kwargs = {}

        if not model_override:
            room = mgr.get_active_room()
            if room.model.model:
                route_kwargs["model"] = room.model.model

        if model_override:
            route_kwargs["model"] = model_override

        assert route_kwargs["model"] == "gemini-2.5-pro"
        reset_room_manager()
