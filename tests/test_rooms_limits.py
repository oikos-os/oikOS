import json

import pytest
from core.rooms.models import RoomConfig, RoomLimits

@pytest.fixture(autouse=True)
def reset_rooms():
    yield
    from core.rooms.manager import reset_room_manager
    reset_room_manager()

class TestRoomLimitsModel:
    def test_default_limits_are_none(self):
        room = RoomConfig(id="test", name="Test")
        assert room.limits.max_tokens_per_query is None
        assert room.limits.max_tool_calls_per_session is None
        assert room.limits.monthly_cloud_budget_cents is None
        assert room.limits.session_isolation is True

    def test_limits_with_values(self):
        room = RoomConfig(
            id="limited", name="Limited",
            limits=RoomLimits(
                max_tokens_per_query=8000,
                max_tool_calls_per_session=50,
                monthly_cloud_budget_cents=500,
            ),
        )
        assert room.limits.max_tokens_per_query == 8000
        assert room.limits.monthly_cloud_budget_cents == 500

    def test_home_room_session_isolation_false(self):
        from core.rooms.defaults import home_room
        home = home_room()
        assert home.limits.session_isolation is False

    def test_negative_limits_rejected(self):
        with pytest.raises(ValueError):
            RoomLimits(max_tokens_per_query=-1)
        with pytest.raises(ValueError):
            RoomLimits(max_tool_calls_per_session=-1)
        with pytest.raises(ValueError):
            RoomLimits(monthly_cloud_budget_cents=-1)

    def test_serialization_roundtrip(self):
        limits = RoomLimits(max_tokens_per_query=4000, monthly_cloud_budget_cents=100)
        room = RoomConfig(id="test", name="Test", limits=limits)
        data = room.model_dump()
        restored = RoomConfig(**data)
        assert restored.limits.max_tokens_per_query == 4000


class TestRoomLimitsEnforcement:
    def test_token_limit_overrides_budget(self, tmp_path, monkeypatch):
        monkeypatch.setattr("core.rooms.manager.ROOMS_DIR", tmp_path / "rooms")
        from core.rooms.manager import get_room_manager
        mgr = get_room_manager(tmp_path / "rooms")
        mgr.create_room(RoomConfig(id="capped", name="Capped", limits=RoomLimits(max_tokens_per_query=2000)))
        mgr.switch_room("capped")
        from core.rooms.limits import check_room_limits
        result = check_room_limits("capped")
        assert result["token_budget_override"] == 2000

    def test_cloud_budget_forces_local(self, tmp_path, monkeypatch):
        monkeypatch.setattr("core.rooms.manager.ROOMS_DIR", tmp_path / "rooms")
        monkeypatch.setattr("core.rooms.limits.COSTS_DIR", tmp_path / "costs")
        from core.rooms.manager import get_room_manager
        from datetime import datetime, timezone
        mgr = get_room_manager(tmp_path / "rooms")
        mgr.create_room(RoomConfig(id="budget", name="Budget", limits=RoomLimits(monthly_cloud_budget_cents=100)))
        mgr.switch_room("budget")
        costs_dir = tmp_path / "costs"
        costs_dir.mkdir()
        ts = datetime.now(timezone.utc).isoformat()
        (costs_dir / "budget.jsonl").write_text(
            json.dumps({"timestamp": ts, "cost_usd": 2.00, "provider": "claude", "model": "test", "tokens": 1000}) + "\n"
        )
        from core.rooms.limits import check_room_limits
        result = check_room_limits("budget")
        assert result["force_local"] is True

    def test_tool_call_limit_blocks(self, tmp_path, monkeypatch):
        monkeypatch.setattr("core.rooms.manager.ROOMS_DIR", tmp_path / "rooms")
        from core.rooms.manager import get_room_manager
        mgr = get_room_manager(tmp_path / "rooms")
        mgr.create_room(RoomConfig(id="limited", name="Limited", limits=RoomLimits(max_tool_calls_per_session=5)))
        mgr.switch_room("limited")
        from core.rooms.limits import check_room_limits
        result = check_room_limits("limited", tool_call_count=6)
        assert result["block_tools"] is True

    def test_tool_call_limit_allows_below(self, tmp_path, monkeypatch):
        monkeypatch.setattr("core.rooms.manager.ROOMS_DIR", tmp_path / "rooms")
        from core.rooms.manager import get_room_manager
        mgr = get_room_manager(tmp_path / "rooms")
        mgr.create_room(RoomConfig(id="limited", name="Limited", limits=RoomLimits(max_tool_calls_per_session=5)))
        mgr.switch_room("limited")
        from core.rooms.limits import check_room_limits
        result = check_room_limits("limited", tool_call_count=3)
        assert result["block_tools"] is False

    def test_no_limits_passthrough(self, tmp_path, monkeypatch):
        monkeypatch.setattr("core.rooms.manager.ROOMS_DIR", tmp_path / "rooms")
        from core.rooms.manager import get_room_manager
        get_room_manager(tmp_path / "rooms")
        from core.rooms.limits import check_room_limits
        result = check_room_limits("home")
        assert result["enforce"] is False

    def test_get_room_usage_returns_fields(self, tmp_path, monkeypatch):
        monkeypatch.setattr("core.rooms.manager.ROOMS_DIR", tmp_path / "rooms")
        monkeypatch.setattr("core.rooms.limits.COSTS_DIR", tmp_path / "costs")
        from core.rooms.manager import get_room_manager
        get_room_manager(tmp_path / "rooms")
        from core.rooms.limits import get_room_usage
        usage = get_room_usage("home")
        assert "monthly_cloud_spend_cents" in usage
        assert "monthly_tokens" in usage
        assert "room_id" in usage

    def test_log_room_cost_creates_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr("core.rooms.limits.COSTS_DIR", tmp_path / "costs")
        from core.rooms.limits import log_room_cost
        log_room_cost("test-room", "claude", "model", 0.50, 1000)
        assert (tmp_path / "costs" / "test-room.jsonl").exists()
        line = (tmp_path / "costs" / "test-room.jsonl").read_text().strip()
        data = json.loads(line)
        assert data["cost_usd"] == 0.50
        assert data["tokens"] == 1000
