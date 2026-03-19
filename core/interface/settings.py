"""Runtime settings with JSON persistence — overlay on top of config.py defaults."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from threading import Lock

from core.interface.config import PROJECT_ROOT

log = logging.getLogger(__name__)

SETTINGS_FILE = PROJECT_ROOT / "settings.json"

# Keys that can be overridden at runtime (whitelist)
MUTABLE_KEYS: set[str] = {
    "inference_model",
    "default_token_budget",
    "inference_temperature",
    "inference_top_p",
    "inference_max_tokens",
    "cloud_model",
    "cloud_routing_posture",
    "credits_monthly_cap",
    "pii_confidence_threshold",
    "routing_confidence_threshold",
    "embed_batch_size",
    "provider_default",
    "provider_cloud_default",
    "provider_anthropic_model",
    "onboarding_complete",
    "onboarding_step",
}

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


def get_setting(key: str) -> object:
    """Get a runtime-overridden setting, falling back to config.py default."""
    _ensure_loaded()
    if key in _overrides:
        return _overrides[key]
    from core.interface import config
    config_key = key.upper()
    if hasattr(config, config_key):
        return getattr(config, config_key)
    raise KeyError(f"Unknown setting: {key}")


def update_setting(key: str, value: object) -> None:
    """Update a runtime setting and persist to disk."""
    if key not in MUTABLE_KEYS:
        raise ValueError(f"Setting '{key}' is not mutable. Allowed: {sorted(MUTABLE_KEYS)}")
    _ensure_loaded()
    with _lock:
        _overrides[key] = value
        _persist()
    log.info("Setting updated: %s = %r", key, value)


def get_all_settings() -> dict[str, object]:
    """Return all mutable settings with their current effective values."""
    _ensure_loaded()
    result = {}
    from core.interface import config
    for key in sorted(MUTABLE_KEYS):
        if key in _overrides:
            result[key] = _overrides[key]
        else:
            config_key = key.upper()
            result[key] = getattr(config, config_key, None)
    return result


def reset_setting(key: str) -> None:
    """Remove a runtime override, reverting to config.py default."""
    _ensure_loaded()
    with _lock:
        _overrides.pop(key, None)
        _persist()
