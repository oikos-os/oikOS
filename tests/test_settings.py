"""Tests for core.interface.settings — runtime settings with JSON persistence."""

import json
import pytest
from unittest.mock import patch

from core.interface.settings import (
    get_setting,
    update_setting,
    get_all_settings,
    reset_setting,
    MUTABLE_KEYS,
    _overrides,
    SETTINGS_FILE,
)
from core.interface import config


@pytest.fixture(autouse=True)
def _clean_overrides():
    """Reset overrides between tests."""
    import core.interface.settings as mod
    mod._overrides.clear()
    mod._loaded = True  # skip file load
    yield
    mod._overrides.clear()


class TestGetSetting:
    def test_returns_config_default(self):
        assert get_setting("inference_model") == config.INFERENCE_MODEL

    def test_returns_override_over_default(self):
        _overrides["inference_model"] = "test-model:7b"
        assert get_setting("inference_model") == "test-model:7b"

    def test_raises_on_unknown_key(self):
        with pytest.raises(KeyError, match="Unknown setting"):
            get_setting("nonexistent_key_xyz")


class TestUpdateSetting:
    def test_updates_and_persists(self, tmp_path, monkeypatch):
        settings_file = tmp_path / "settings.json"
        monkeypatch.setattr("core.interface.settings.SETTINGS_FILE", settings_file)

        update_setting("inference_model", "qwen2.5:7b")
        assert _overrides["inference_model"] == "qwen2.5:7b"
        assert settings_file.exists()
        data = json.loads(settings_file.read_text())
        assert data["inference_model"] == "qwen2.5:7b"

    def test_rejects_immutable_key(self):
        with pytest.raises(ValueError, match="not mutable"):
            update_setting("project_root", "/tmp")

    def test_rejects_unknown_key(self):
        with pytest.raises(ValueError, match="not mutable"):
            update_setting("totally_fake_key", 42)


class TestGetAllSettings:
    def test_returns_all_mutable_keys(self):
        result = get_all_settings()
        assert set(result.keys()) == MUTABLE_KEYS

    def test_reflects_overrides(self):
        _overrides["inference_model"] = "override-model"
        result = get_all_settings()
        assert result["inference_model"] == "override-model"


class TestResetSetting:
    def test_removes_override(self, tmp_path, monkeypatch):
        settings_file = tmp_path / "settings.json"
        monkeypatch.setattr("core.interface.settings.SETTINGS_FILE", settings_file)

        _overrides["inference_model"] = "custom"
        reset_setting("inference_model")
        assert "inference_model" not in _overrides
        assert get_setting("inference_model") == config.INFERENCE_MODEL


class TestFileLoad:
    def test_loads_from_disk(self, tmp_path, monkeypatch):
        import core.interface.settings as mod
        settings_file = tmp_path / "settings.json"
        settings_file.write_text(json.dumps({"inference_model": "from-disk"}))
        monkeypatch.setattr(mod, "SETTINGS_FILE", settings_file)
        mod._overrides.clear()
        mod._loaded = False
        assert get_setting("inference_model") == "from-disk"

    def test_handles_missing_file(self, tmp_path, monkeypatch):
        import core.interface.settings as mod
        monkeypatch.setattr(mod, "SETTINGS_FILE", tmp_path / "missing.json")
        mod._overrides.clear()
        mod._loaded = False
        # Should not raise, falls through to config defaults
        assert get_setting("inference_model") == config.INFERENCE_MODEL

    def test_handles_corrupted_file(self, tmp_path, monkeypatch):
        """SYNTH ruling: garbage in settings.json must fall back to config.py defaults."""
        import core.interface.settings as mod
        settings_file = tmp_path / "settings.json"
        settings_file.write_text("NOT VALID JSON {{{garbage!!!")
        monkeypatch.setattr(mod, "SETTINGS_FILE", settings_file)
        mod._overrides.clear()
        mod._loaded = False
        assert get_setting("default_token_budget") == config.DEFAULT_TOKEN_BUDGET
        assert get_setting("inference_model") == config.INFERENCE_MODEL
