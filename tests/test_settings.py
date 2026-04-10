"""Tests for core.interface.settings — runtime settings with JSON persistence."""

import json
import pytest
from unittest.mock import patch

from core.interface.settings import (
    get_setting,
    update_setting,
    get_all_settings,
    reset_setting,
    _overrides,
    SETTINGS_FILE,
)
from core.interface import config
from core.interface.settings_registry import SETTINGS_REGISTRY


@pytest.fixture(autouse=True)
def _clean_overrides():
    """Reset overrides between tests."""
    import core.interface.settings as mod
    mod._overrides.clear()
    mod._loaded = True  # skip file load
    yield
    mod._overrides.clear()


class TestGetSetting:
    def test_returns_registry_default(self):
        assert get_setting("inference_temperature") == 0.7

    def test_returns_override_over_default(self):
        _overrides["inference_temperature"] = 0.5
        assert get_setting("inference_temperature") == 0.5

    def test_raises_on_unknown_key(self):
        with pytest.raises(KeyError, match="Unknown setting"):
            get_setting("nonexistent_key_xyz")


class TestUpdateSetting:
    def test_updates_and_persists(self, tmp_path, monkeypatch):
        settings_file = tmp_path / "settings.json"
        monkeypatch.setattr("core.interface.settings.SETTINGS_FILE", settings_file)

        result = update_setting("inference_temperature", 1.2)
        assert _overrides["inference_temperature"] == 1.2
        assert result["applied"] is True
        assert settings_file.exists()
        data = json.loads(settings_file.read_text())
        assert data["inference_temperature"] == 1.2

    def test_rejects_invalid_value(self):
        with pytest.raises(ValueError):
            update_setting("inference_temperature", 99.0)

    def test_rejects_unknown_key(self):
        with pytest.raises(KeyError, match="Unknown setting"):
            update_setting("totally_fake_key", 42)


class TestGetAllSettings:
    def test_returns_all_registry_keys(self):
        result = get_all_settings()
        assert set(result.keys()) == set(SETTINGS_REGISTRY.keys())

    def test_reflects_overrides(self):
        _overrides["inference_temperature"] = 0.3
        result = get_all_settings()
        assert result["inference_temperature"] == 0.3


class TestResetSetting:
    def test_removes_override(self, tmp_path, monkeypatch):
        settings_file = tmp_path / "settings.json"
        monkeypatch.setattr("core.interface.settings.SETTINGS_FILE", settings_file)

        _overrides["inference_temperature"] = 0.3
        reset_setting("inference_temperature")
        assert "inference_temperature" not in _overrides
        assert get_setting("inference_temperature") == 0.7


class TestFileLoad:
    def test_loads_from_disk(self, tmp_path, monkeypatch):
        import core.interface.settings as mod
        settings_file = tmp_path / "settings.json"
        settings_file.write_text(json.dumps({"inference_temperature": 0.9}))
        monkeypatch.setattr(mod, "SETTINGS_FILE", settings_file)
        mod._overrides.clear()
        mod._loaded = False
        assert get_setting("inference_temperature") == 0.9

    def test_handles_missing_file(self, tmp_path, monkeypatch):
        import core.interface.settings as mod
        monkeypatch.setattr(mod, "SETTINGS_FILE", tmp_path / "missing.json")
        mod._overrides.clear()
        mod._loaded = False
        # Should not raise, falls through to registry defaults
        assert get_setting("inference_temperature") == 0.7

    def test_handles_corrupted_file(self, tmp_path, monkeypatch):
        """Garbage in settings.json must fall back to registry defaults."""
        import core.interface.settings as mod
        settings_file = tmp_path / "settings.json"
        settings_file.write_text("NOT VALID JSON {{{garbage!!!")
        monkeypatch.setattr(mod, "SETTINGS_FILE", settings_file)
        mod._overrides.clear()
        mod._loaded = False
        assert get_setting("inference_temperature") == 0.7
        assert get_setting("cloud_routing_posture") == "balanced"
