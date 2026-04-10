"""Tests for T-109 Gate 3: Room personality and template updates."""

import pytest
from core.rooms.models import RoomConfig, RoomVoice, RoomLimits
from core.rooms.defaults import TEMPLATES


class TestRoomPersonality:
    def test_personality_field_exists(self):
        voice = RoomVoice()
        assert voice.personality is None

    def test_personality_can_be_set(self):
        voice = RoomVoice(personality="Be concise and professional.")
        assert voice.personality == "Be concise and professional."

    def test_room_with_personality(self):
        room = RoomConfig(
            id="test-room",
            name="Test",
            voice={"personality": "You are a focused assistant."},
        )
        assert room.voice.personality == "You are a focused assistant."

    def test_room_without_personality_backward_compat(self):
        room = RoomConfig(id="test-room", name="Test")
        assert room.voice.personality is None

    def test_personality_in_voice_model(self):
        room = RoomConfig(
            id="test-room",
            name="Test",
            voice={
                "system_prompt": "You are helpful.",
                "personality": "Be brief.",
                "temperature": 0.7,
            },
        )
        assert room.voice.system_prompt == "You are helpful."
        assert room.voice.personality == "Be brief."
        assert room.voice.temperature == 0.7


class TestTemplatePersonalities:
    def test_researcher_has_personality(self):
        assert "personality" in TEMPLATES["researcher"]["voice"]
        assert "thorough" in TEMPLATES["researcher"]["voice"]["personality"].lower()

    def test_code_has_personality(self):
        assert "personality" in TEMPLATES["code"]["voice"]
        assert "concise" in TEMPLATES["code"]["voice"]["personality"].lower()

    def test_writing_has_personality(self):
        assert "personality" in TEMPLATES["writing"]["voice"]
        assert "prose" in TEMPLATES["writing"]["voice"]["personality"].lower()

    def test_health_has_personality(self):
        assert "personality" in TEMPLATES["health"]["voice"]
        assert "medical" in TEMPLATES["health"]["voice"]["personality"].lower()

    def test_finance_has_personality(self):
        assert "personality" in TEMPLATES["finance"]["voice"]
        assert "financial advice" in TEMPLATES["finance"]["voice"]["personality"].lower()

    def test_all_templates_have_personality(self):
        for name, template in TEMPLATES.items():
            voice = template.get("voice", {})
            assert "personality" in voice, f"Template '{name}' missing personality"
            assert len(voice["personality"]) > 20, f"Template '{name}' personality too short"


class TestVaultIndexLimit:
    def test_field_exists_with_default(self):
        limits = RoomLimits()
        assert limits.vault_index_limit is None

    def test_valid_limit(self):
        limits = RoomLimits(vault_index_limit=50)
        assert limits.vault_index_limit == 50

    def test_minimum_enforced(self):
        with pytest.raises(ValueError, match="minimum is 10"):
            RoomLimits(vault_index_limit=5)

    def test_maximum_enforced(self):
        with pytest.raises(ValueError, match="maximum is 500"):
            RoomLimits(vault_index_limit=600)

    def test_boundary_values(self):
        assert RoomLimits(vault_index_limit=10).vault_index_limit == 10
        assert RoomLimits(vault_index_limit=500).vault_index_limit == 500
