"""Tests for T-117: settings integration — write/read roundtrip, defaults, validation."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def isolated_settings(tmp_path, monkeypatch):
    """Use a temporary settings.json for each test."""
    settings_file = tmp_path / "settings.json"
    settings_file.write_text("{}")
    monkeypatch.setattr("core.interface.settings.SETTINGS_FILE", settings_file)
    import core.interface.settings as mod
    mod._overrides.clear()
    mod._loaded = False
    yield settings_file


def test_setting_write_roundtrip(isolated_settings):
    from core.interface.settings import get_setting, update_setting
    update_setting("inference_temperature", 1.5)
    assert get_setting("inference_temperature") == 1.5


def test_setting_defaults_match_registry(isolated_settings):
    from core.interface.settings import get_setting
    from core.interface.settings_registry import SETTINGS_REGISTRY
    for key, defn in SETTINGS_REGISTRY.items():
        val = get_setting(key)
        assert val == defn.default, f"{key}: got {val!r}, expected {defn.default!r}"


def test_setting_affects_behavior(isolated_settings):
    from core.interface.settings import update_setting
    update_setting("inference_temperature", 0.1)
    update_setting("cloud_routing_posture", "aggressive")
    from core.cognition.complexity import score_complexity
    result = score_complexity("hello")
    assert result["skip_local"] is False


def test_invalid_setting_rejected(isolated_settings):
    from core.interface.settings import update_setting
    with pytest.raises(ValueError, match="Must be"):
        update_setting("inference_temperature", 99.0)


def test_unknown_setting_rejected(isolated_settings):
    from core.interface.settings import update_setting
    with pytest.raises(KeyError, match="Unknown setting"):
        update_setting("nonexistent_key", 42)
