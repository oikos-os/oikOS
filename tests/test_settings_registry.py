"""Tests for T-117: settings registry — tier definitions, validators, metadata."""

from __future__ import annotations

import pytest

from core.interface.settings_registry import (
    SETTINGS_REGISTRY,
    SettingDef,
    SettingTier,
    get_settings_by_tier,
    validate_setting,
)


def test_all_settings_have_validators():
    for key, defn in SETTINGS_REGISTRY.items():
        assert callable(defn.validator), f"{key} missing callable validator"
        assert defn.error_hint, f"{key} missing error_hint"


def test_essential_tier_count():
    essential = get_settings_by_tier(SettingTier.ESSENTIAL)
    assert len(essential) == 8


def test_validate_routing_posture_valid():
    for v in ("conservative", "balanced", "aggressive"):
        ok, _ = validate_setting("cloud_routing_posture", v)
        assert ok, f"{v} should be valid"


def test_validate_routing_posture_invalid():
    ok, msg = validate_setting("cloud_routing_posture", "turbo")
    assert not ok
    assert "conservative" in msg or "balanced" in msg


def test_validate_temperature_range():
    ok, _ = validate_setting("inference_temperature", 0.0)
    assert ok
    ok, _ = validate_setting("inference_temperature", 2.0)
    assert ok
    ok, _ = validate_setting("inference_temperature", -1)
    assert not ok
    ok, _ = validate_setting("inference_temperature", 3.0)
    assert not ok


def test_validate_max_tokens_range():
    ok, _ = validate_setting("inference_max_tokens", 256)
    assert ok
    ok, _ = validate_setting("inference_max_tokens", 32768)
    assert ok
    ok, _ = validate_setting("inference_max_tokens", 0)
    assert not ok
    ok, _ = validate_setting("inference_max_tokens", 100000)
    assert not ok


def test_validate_timeout_range():
    # idle_timeout: 1-120
    ok, _ = validate_setting("idle_timeout", 1)
    assert ok
    ok, _ = validate_setting("idle_timeout", 120)
    assert ok
    ok, _ = validate_setting("idle_timeout", 0)
    assert not ok
    # session_timeout: 5-180
    ok, _ = validate_setting("session_timeout", 5)
    assert ok
    ok, _ = validate_setting("session_timeout", 180)
    assert ok
    ok, _ = validate_setting("session_timeout", 4)
    assert not ok


def test_get_settings_by_tier():
    essential = get_settings_by_tier(SettingTier.ESSENTIAL)
    advanced = get_settings_by_tier(SettingTier.ADVANCED)
    expert = get_settings_by_tier(SettingTier.EXPERT)
    assert len(essential) == 8
    assert len(advanced) == 7  # +3 notification tier settings (T-119 Task 6)
    assert len(expert) == 9
    # No overlap
    all_keys = set(essential) | set(advanced) | set(expert)
    assert len(all_keys) == len(essential) + len(advanced) + len(expert)
