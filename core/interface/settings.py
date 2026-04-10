"""Runtime settings with JSON persistence — overlay on top of registry defaults."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from threading import Lock
from typing import Any

from core.interface.config import PROJECT_ROOT

log = logging.getLogger(__name__)

SETTINGS_FILE = PROJECT_ROOT / "settings.json"

_lock = Lock()
_overrides: dict[str, object] = {}
_loaded = False


def _ensure_loaded() -> None:
    global _loaded
    if _loaded:
        return
    with _lock:
        if _loaded:
            return
        if SETTINGS_FILE.exists():
            try:
                data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
                _overrides.update(data)
                log.info("Loaded %d setting overrides from %s", len(data), SETTINGS_FILE)
            except (json.JSONDecodeError, OSError) as e:
                log.warning("Failed to load settings: %s", e)
        _loaded = True


def _persist() -> None:
    try:
        SETTINGS_FILE.write_text(json.dumps(_overrides, indent=2), encoding="utf-8")
    except OSError as e:
        log.error("Failed to persist settings: %s", e)


def _coerce(value: Any, setting_type: str) -> Any:
    """Coerce string values from CLI/API to the correct Python type."""
    if setting_type == "bool" and isinstance(value, str):
        if value.lower() in ("true", "1", "yes", "on"):
            return True
        if value.lower() in ("false", "0", "no", "off"):
            return False
    if setting_type == "int" and not isinstance(value, bool):
        try:
            return int(value)
        except (ValueError, TypeError):
            pass
    if setting_type == "float" and not isinstance(value, bool):
        try:
            return float(value)
        except (ValueError, TypeError):
            pass
    return value


def get_setting(key: str) -> object:
    """Get a setting: override → registry default → config.py fallback."""
    _ensure_loaded()
    if key in _overrides:
        return _overrides[key]
    from core.interface.settings_registry import SETTINGS_REGISTRY
    if key in SETTINGS_REGISTRY:
        return SETTINGS_REGISTRY[key].default
    # Fallback: config.py uppercase constant (for settings not yet in registry)
    from core.interface import config
    config_key = key.upper()
    if hasattr(config, config_key):
        return getattr(config, config_key)
    raise KeyError(f"Unknown setting: {key}")


def update_setting(key: str, value: Any) -> dict:
    """Validate, coerce, write, and return result with restart_required flag."""
    from core.interface.settings_registry import SETTINGS_REGISTRY, validate_setting

    if key in SETTINGS_REGISTRY:
        defn = SETTINGS_REGISTRY[key]
        value = _coerce(value, defn.setting_type)
        ok, msg = validate_setting(key, value)
        if not ok:
            raise ValueError(msg)
        restart_required = defn.restart_required
    else:
        # Legacy keys not yet in registry — explicit allowlist for backward compat.
        # These will migrate to the registry in future tasks.
        _LEGACY_WRITABLE = {
            "onboarding_complete", "onboarding_step",
            "inference_model", "cloud_model", "default_token_budget",
            "embed_batch_size", "provider_default", "provider_cloud_default",
            "provider_anthropic_model", "routing_confidence_threshold",
            "inference_top_p",
        }
        if key not in _LEGACY_WRITABLE:
            raise KeyError(f"Unknown setting: {key}")
        restart_required = False

    _ensure_loaded()
    with _lock:
        _overrides[key] = value
        _persist()
    log.info("Setting updated: %s = %r", key, value)
    return {"applied": True, "restart_required": restart_required}


def get_all_settings() -> dict[str, object]:
    """Return all registry settings with their current effective values."""
    _ensure_loaded()
    from core.interface.settings_registry import SETTINGS_REGISTRY
    result = {}
    for key, defn in sorted(SETTINGS_REGISTRY.items()):
        if key in _overrides:
            result[key] = _overrides[key]
        else:
            result[key] = defn.default
    return result


def get_tiered_settings() -> dict[str, dict]:
    """Return settings organized by tier with metadata for API/UI."""
    _ensure_loaded()
    from core.interface.settings_registry import SETTINGS_REGISTRY, SettingTier
    tiers: dict[str, dict] = {"essential": {}, "advanced": {}, "expert": {}}
    for key, defn in SETTINGS_REGISTRY.items():
        current = _overrides.get(key, defn.default)
        tiers[defn.tier.value][key] = defn.to_api_dict(current)
    return tiers


def reset_setting(key: str) -> None:
    """Remove a runtime override, reverting to registry default."""
    _ensure_loaded()
    with _lock:
        _overrides.pop(key, None)
        _persist()
