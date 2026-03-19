import pytest
from core.rooms.models import RoomConfig, RoomVaultScope, RoomAutonomy, RoomModelConfig, RoomVoice


class TestRoomConfig:
    def test_minimal_room(self):
        room = RoomConfig(id="test", name="Test Room")
        assert room.id == "test"
        assert room.vault_scope.mode == "all"
        assert room.toolsets is None  # None = all
        assert room.autonomy.overrides == {}

    def test_full_room(self):
        room = RoomConfig(
            id="researcher",
            name="Researcher",
            description="ML research assistant",
            vault_scope=RoomVaultScope(mode="include", paths=["knowledge/ml/"]),
            toolsets=["vault", "browser", "research"],
            autonomy=RoomAutonomy(overrides={"web_navigate": "ASK_FIRST"}),
            model=RoomModelConfig(provider="ollama", model="qwen2.5:14b"),
            voice=RoomVoice(system_prompt="You are a research assistant.", temperature=0.3),
        )
        assert room.toolsets == ["vault", "browser", "research"]

    def test_invalid_id_uppercase(self):
        with pytest.raises(ValueError):
            RoomConfig(id="MyRoom", name="Bad")

    def test_invalid_id_too_long(self):
        with pytest.raises(ValueError):
            RoomConfig(id="a" * 33, name="Bad")

    def test_invalid_id_special_chars(self):
        with pytest.raises(ValueError):
            RoomConfig(id="my room!", name="Bad")

    def test_valid_id_hyphens_underscores(self):
        room = RoomConfig(id="my-research_room", name="OK")
        assert room.id == "my-research_room"

    def test_serialization_roundtrip(self):
        room = RoomConfig(id="test", name="Test", description="A test room")
        data = room.model_dump()
        restored = RoomConfig(**data)
        assert restored == room

    def test_vault_scope_modes(self):
        for mode in ("all", "include", "exclude"):
            scope = RoomVaultScope(mode=mode)
            assert scope.mode == mode

    def test_vault_scope_invalid_mode(self):
        with pytest.raises(ValueError):
            RoomVaultScope(mode="invalid")

    def test_autonomy_overrides_valid_values(self):
        auto = RoomAutonomy(overrides={"fs_delete": "PROHIBITED", "web_navigate": "ASK_FIRST"})
        assert auto.overrides["fs_delete"] == "PROHIBITED"

    def test_autonomy_overrides_invalid_value(self):
        with pytest.raises(ValueError):
            RoomAutonomy(overrides={"fs_delete": "YOLO"})
