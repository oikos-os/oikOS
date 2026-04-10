# T-117: Settings Exposure — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Organize all user-tunable settings into a tiered registry, extract hardcoded values, and expose them via API, TUI, and CLI.

**Architecture:** A `SettingDef` registry in `settings_registry.py` is the single source of truth for all 21 settings across 3 tiers. `get_setting()` falls back to registry defaults instead of `config.py` attributes. All consumers read inside functions for hot-reload. The API returns tier-structured metadata, TUI adds Essential+Advanced sections, CLI replaces the T-104 allowlist with registry filters.

**Tech Stack:** Python 3.12, FastAPI, Textual, Click, pytest

---

## File Structure

| File | Responsibility |
|---|---|
| `core/interface/settings_registry.py` | CREATE — SettingDef dataclass, SETTINGS_REGISTRY dict, tier helpers, validation |
| `core/interface/settings.py` | MODIFY — fallback chain uses registry, validate on write, type coercion |
| `core/interface/config.py` | MODIFY — remove extracted constants (keep non-extracted ones) |
| `core/cognition/complexity.py` | MODIFY — read posture/threshold inside `score_complexity()` |
| `core/memory/session.py` | MODIFY — read timeout inside `_is_expired()` |
| `core/autonomic/daemon.py` | MODIFY — read idle timeout inside heartbeat function |
| `core/interface/api/routes/settings.py` | MODIFY — tier-structured GET, validated PUT |
| `core/interface/tui/views/settings.py` | MODIFY — Essential+Advanced+Connections sections |
| `core/interface/cli.py` | MODIFY — replace T-104 allowlist with registry filter |
| `tests/test_settings_registry.py` | CREATE — 8 registry unit tests |
| `tests/test_settings_integration.py` | CREATE — 5 integration tests |
| `tests/test_cli_t104.py` | MODIFY — 4 new CLI config tests |

---

## Task 1: Settings Registry Module

**Files:**
- Create: `core/interface/settings_registry.py`
- Test: `tests/test_settings_registry.py`

- [ ] **Step 1: Write the registry tests**

Create `tests/test_settings_registry.py`:

```python
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
    assert len(advanced) == 4
    assert len(expert) == 9
    # No overlap
    all_keys = set(essential) | set(advanced) | set(expert)
    assert len(all_keys) == len(essential) + len(advanced) + len(expert)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_settings_registry.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.interface.settings_registry'`

- [ ] **Step 3: Create the settings registry module**

Create `core/interface/settings_registry.py`:

```python
"""Settings registry — single source of truth for setting metadata and validation.

Three tiers:
  - Essential: TUI + CLI + API (user-facing knobs)
  - Advanced: TUI + API (power-user tuning)
  - Expert: settings.json only (codebase-level)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable


class SettingTier(Enum):
    ESSENTIAL = "essential"
    ADVANCED = "advanced"
    EXPERT = "expert"


@dataclass
class SettingDef:
    key: str
    tier: SettingTier
    setting_type: str  # "int", "float", "bool", "enum"
    default: Any
    description: str
    validator: Callable[[Any], bool]
    error_hint: str
    min_val: float | None = None
    max_val: float | None = None
    options: list[str] | None = None
    restart_required: bool = False

    def to_api_dict(self, current_value: Any) -> dict:
        """Serializable metadata for UI widget construction."""
        d: dict[str, Any] = {
            "value": current_value,
            "type": self.setting_type,
            "description": self.description,
            "restart_required": self.restart_required,
        }
        if self.min_val is not None:
            d["min"] = self.min_val
        if self.max_val is not None:
            d["max"] = self.max_val
        if self.options is not None:
            d["options"] = self.options
        return d


def _in_range(v: Any, lo: float, hi: float) -> bool:
    try:
        return lo <= float(v) <= hi
    except (ValueError, TypeError):
        return False


SETTINGS_REGISTRY: dict[str, SettingDef] = {
    # ── Essential ────────────────────────────────────────────────
    "cloud_routing_posture": SettingDef(
        key="cloud_routing_posture",
        tier=SettingTier.ESSENTIAL,
        setting_type="enum",
        default="balanced",
        description="How aggressively queries route to cloud",
        validator=lambda v: v in ("conservative", "balanced", "aggressive"),
        error_hint="Must be 'conservative', 'balanced', or 'aggressive'",
        options=["conservative", "balanced", "aggressive"],
    ),
    "inference_temperature": SettingDef(
        key="inference_temperature",
        tier=SettingTier.ESSENTIAL,
        setting_type="float",
        default=0.7,
        description="Default generation temperature",
        validator=lambda v: _in_range(v, 0.0, 2.0),
        error_hint="Must be a number between 0.0 and 2.0",
        min_val=0.0,
        max_val=2.0,
    ),
    "inference_max_tokens": SettingDef(
        key="inference_max_tokens",
        tier=SettingTier.ESSENTIAL,
        setting_type="int",
        default=2048,
        description="Default max response tokens",
        validator=lambda v: _in_range(v, 256, 32768),
        error_hint="Must be an integer between 256 and 32768",
        min_val=256,
        max_val=32768,
    ),
    "theme": SettingDef(
        key="theme",
        tier=SettingTier.ESSENTIAL,
        setting_type="enum",
        default="amber",
        description="Color theme",
        validator=lambda v: v in ("amber", "green", "white"),
        error_hint="Must be 'amber', 'green', or 'white'",
        options=["amber", "green", "white"],
    ),
    "idle_timeout": SettingDef(
        key="idle_timeout",
        tier=SettingTier.ESSENTIAL,
        setting_type="int",
        default=15,
        description="Minutes before IDLE cascade",
        validator=lambda v: _in_range(v, 1, 120),
        error_hint="Must be an integer between 1 and 120",
        min_val=1,
        max_val=120,
    ),
    "session_timeout": SettingDef(
        key="session_timeout",
        tier=SettingTier.ESSENTIAL,
        setting_type="int",
        default=30,
        description="Minutes before session auto-close",
        validator=lambda v: _in_range(v, 5, 180),
        error_hint="Must be an integer between 5 and 180",
        min_val=5,
        max_val=180,
    ),
    "boot_quote": SettingDef(
        key="boot_quote",
        tier=SettingTier.ESSENTIAL,
        setting_type="bool",
        default=True,
        description="Show doctrine quote on boot",
        validator=lambda v: isinstance(v, bool),
        error_hint="Must be true or false",
    ),
    "notifications": SettingDef(
        key="notifications",
        tier=SettingTier.ESSENTIAL,
        setting_type="bool",
        default=True,
        description="Enable notifications",
        validator=lambda v: isinstance(v, bool),
        error_hint="Must be true or false",
    ),
    # ── Advanced ─────────────────────────────────────────────────
    "pii_confidence_threshold": SettingDef(
        key="pii_confidence_threshold",
        tier=SettingTier.ADVANCED,
        setting_type="float",
        default=0.3,
        description="PII detection confidence threshold",
        validator=lambda v: _in_range(v, 0.0, 1.0),
        error_hint="Must be a number between 0.0 and 1.0",
        min_val=0.0,
        max_val=1.0,
    ),
    "credits_monthly_cap": SettingDef(
        key="credits_monthly_cap",
        tier=SettingTier.ADVANCED,
        setting_type="float",
        default=1000000,
        description="Monthly cloud spending limit",
        validator=lambda v: _in_range(v, 0, 1e9),
        error_hint="Must be a non-negative number",
        min_val=0,
    ),
    "approval_timeout": SettingDef(
        key="approval_timeout",
        tier=SettingTier.ADVANCED,
        setting_type="int",
        default=300,
        description="ASK_FIRST proposal expiry (seconds)",
        validator=lambda v: _in_range(v, 30, 3600),
        error_hint="Must be an integer between 30 and 3600",
        min_val=30,
        max_val=3600,
    ),
    "vault_search_weight": SettingDef(
        key="vault_search_weight",
        tier=SettingTier.ADVANCED,
        setting_type="float",
        default=0.7,
        description="Vector vs BM25 balance (0=all BM25, 1=all vector)",
        validator=lambda v: _in_range(v, 0.0, 1.0),
        error_hint="Must be a number between 0.0 and 1.0",
        min_val=0.0,
        max_val=1.0,
    ),
    # ── Expert ───────────────────────────────────────────────────
    "complexity_length_threshold": SettingDef(
        key="complexity_length_threshold",
        tier=SettingTier.EXPERT,
        setting_type="int",
        default=50,
        description="Token count threshold for complexity length signal",
        validator=lambda v: _in_range(v, 1, 500),
        error_hint="Must be a positive integer up to 500",
        min_val=1,
        max_val=500,
    ),
    "cosine_sensitivity": SettingDef(
        key="cosine_sensitivity",
        tier=SettingTier.EXPERT,
        setting_type="float",
        default=0.75,
        description="Sovereign query cosine detection threshold",
        validator=lambda v: _in_range(v, 0.0, 1.0),
        error_hint="Must be a number between 0.0 and 1.0",
        min_val=0.0,
        max_val=1.0,
    ),
    "research_dedup_threshold": SettingDef(
        key="research_dedup_threshold",
        tier=SettingTier.EXPERT,
        setting_type="float",
        default=0.85,
        description="Vault dedup cosine similarity threshold",
        validator=lambda v: _in_range(v, 0.0, 1.0),
        error_hint="Must be a number between 0.0 and 1.0",
        min_val=0.0,
        max_val=1.0,
    ),
    "browser_rate_limit": SettingDef(
        key="browser_rate_limit",
        tier=SettingTier.EXPERT,
        setting_type="float",
        default=2.0,
        description="Browser tool rate limit (requests/second)",
        validator=lambda v: _in_range(v, 0.1, 20.0),
        error_hint="Must be a number between 0.1 and 20.0",
        min_val=0.1,
        max_val=20.0,
    ),
    "recency_half_life": SettingDef(
        key="recency_half_life",
        tier=SettingTier.EXPERT,
        setting_type="int",
        default=90,
        description="Recency decay half-life (days)",
        validator=lambda v: _in_range(v, 1, 365),
        error_hint="Must be an integer between 1 and 365",
        min_val=1,
        max_val=365,
    ),
    "scanner_resonance": SettingDef(
        key="scanner_resonance",
        tier=SettingTier.EXPERT,
        setting_type="float",
        default=60.0,
        description="Scanner resonance threshold",
        validator=lambda v: _in_range(v, 1.0, 100.0),
        error_hint="Must be a number between 1.0 and 100.0",
        min_val=1.0,
        max_val=100.0,
    ),
    "drift_inactivity_days": SettingDef(
        key="drift_inactivity_days",
        tier=SettingTier.EXPERT,
        setting_type="int",
        default=3,
        description="Days of project inactivity before drift nudge",
        validator=lambda v: _in_range(v, 1, 90),
        error_hint="Must be an integer between 1 and 90",
        min_val=1,
        max_val=90,
    ),
    "api_port": SettingDef(
        key="api_port",
        tier=SettingTier.EXPERT,
        setting_type="int",
        default=8420,
        description="API server port",
        validator=lambda v: _in_range(v, 1024, 65535),
        error_hint="Must be an integer between 1024 and 65535",
        min_val=1024,
        max_val=65535,
        restart_required=True,
    ),
    "rpg_overlay": SettingDef(
        key="rpg_overlay",
        tier=SettingTier.EXPERT,
        setting_type="bool",
        default=False,
        description="Enable RPG overlay in responses",
        validator=lambda v: isinstance(v, bool),
        error_hint="Must be true or false",
    ),
}


def get_settings_by_tier(tier: SettingTier) -> dict[str, SettingDef]:
    return {k: v for k, v in SETTINGS_REGISTRY.items() if v.tier == tier}


def validate_setting(key: str, value: Any) -> tuple[bool, str]:
    if key not in SETTINGS_REGISTRY:
        return False, f"Unknown setting '{key}'. Run 'oikos config' to see available settings."
    defn = SETTINGS_REGISTRY[key]
    try:
        if not defn.validator(value):
            return False, defn.error_hint
    except (ValueError, TypeError):
        return False, defn.error_hint
    return True, ""


def get_registry_default(key: str) -> Any:
    if key not in SETTINGS_REGISTRY:
        raise KeyError(f"Unknown setting: {key}")
    return SETTINGS_REGISTRY[key].default
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_settings_registry.py -v`
Expected: 8 passed

- [ ] **Step 5: Commit**

```bash
git add core/interface/settings_registry.py tests/test_settings_registry.py
git commit -m "feat: settings registry with 21 settings across 3 tiers (T-117)"
```

---

## Task 2: Settings Storage — Registry Integration + Hot-Reload

**Files:**
- Modify: `core/interface/settings.py` (full file, lines 1-109)
- Modify: `core/interface/config.py:59-66,87,116,125,133-141,176,194,230` (remove extracted constants)
- Modify: `core/cognition/complexity.py:17-24,85-136` (function-level reads)
- Modify: `core/memory/session.py:31,100-102` (function-level read)
- Modify: `core/autonomic/daemon.py:24,104-105` (function-level read)
- Test: `tests/test_settings_integration.py`

- [ ] **Step 1: Write the integration tests**

Create `tests/test_settings_integration.py`:

```python
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
    # Reset module-level state
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
    # Verify complexity scorer reads posture at call time
    update_setting("cloud_routing_posture", "aggressive")
    from core.cognition.complexity import score_complexity
    result = score_complexity("hello")
    # With aggressive posture, threshold is 5.0 — even 0 penalty shouldn't skip
    assert result["skip_local"] is False


def test_invalid_setting_rejected(isolated_settings):
    from core.interface.settings import update_setting
    with pytest.raises(ValueError, match="Must be"):
        update_setting("inference_temperature", 99.0)


def test_unknown_setting_rejected(isolated_settings):
    from core.interface.settings import update_setting
    with pytest.raises(KeyError, match="Unknown setting"):
        update_setting("nonexistent_key", 42)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_settings_integration.py -v`
Expected: FAIL — `update_setting` still uses `MUTABLE_KEYS` check, not registry validation

- [ ] **Step 3: Modify `core/interface/settings.py` — registry-based fallback + validation**

Replace the full module contents. Key changes:
- Remove `MUTABLE_KEYS` set
- `get_setting()` fallback: `_overrides` → registry default → `KeyError`
- `update_setting()` validates via registry before writing, coerces types
- `get_all_settings()` iterates registry keys, not `MUTABLE_KEYS`
- New `get_tiered_settings()` returns tier-structured dict for API

```python
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
    """Get a setting: override from settings.json, then registry default."""
    _ensure_loaded()
    if key in _overrides:
        return _overrides[key]
    from core.interface.settings_registry import get_registry_default
    return get_registry_default(key)


def update_setting(key: str, value: Any) -> dict:
    """Validate, coerce, write, and return result with restart_required flag."""
    from core.interface.settings_registry import SETTINGS_REGISTRY, validate_setting

    if key not in SETTINGS_REGISTRY:
        raise KeyError(f"Unknown setting: {key}")

    defn = SETTINGS_REGISTRY[key]
    value = _coerce(value, defn.setting_type)
    ok, msg = validate_setting(key, value)
    if not ok:
        raise ValueError(msg)

    _ensure_loaded()
    with _lock:
        _overrides[key] = value
        _persist()
    log.info("Setting updated: %s = %r", key, value)
    return {"applied": True, "restart_required": defn.restart_required}


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
```

- [ ] **Step 4: Remove extracted constants from `config.py`**

In `core/interface/config.py`, remove the following constants that are now in the registry (keep all other constants unchanged):

Remove lines 59 and 62 (inference defaults — keep `INFERENCE_TOP_P` and `INFERENCE_TIMEOUT_SECONDS`):
```
INFERENCE_TEMPERATURE = 0.7
INFERENCE_MAX_TOKENS = 2048
```

Remove line 66 (PII threshold — keep `PII_ENTITY_TYPES` etc.):
```
PII_CONFIDENCE_THRESHOLD = 0.3
```

Remove line 87 (cosine sensitivity — keep `ROUTING_COSINE_ENTITY_DELTA`):
```
ROUTING_COSINE_SENSITIVITY_THRESHOLD = 0.75
```

Remove line 92 (credits cap — keep `CREDITS_FILE` and `CREDITS_RESET_DAY`):
```
CREDITS_MONTHLY_CAP = 1000000
```

Remove line 116 (scanner resonance — keep other scanner constants):
```
SCANNER_RESONANCE_THRESHOLD = 60.0
```

Remove lines 120-141 (entire Cloud Routing Posture + Complexity section — keep the posture thresholds map as a plain dict for use by complexity scorer):

Replace the block from `# ── Cloud Routing Posture` through `COMPLEXITY_SKIP_LOCAL_THRESHOLD = ...` with:

```python
# ── Posture Thresholds (used by complexity scorer) ──────────────────
# Maps posture name → skip_local complexity threshold.
# The posture value itself is stored in settings_registry.
POSTURE_THRESHOLDS = {"conservative": 35.0, "balanced": 20.0, "aggressive": 5.0}
```

Remove line 176 (daemon idle timeout — keep other daemon constants):
```
DAEMON_IDLE_TIMEOUT_MINUTES = 15
```

Remove line 194 (API port — keep `API_VERSION`):
```
API_DEFAULT_PORT = 8420
```

Remove line 230 (approval timeout — keep `APPROVAL_PROPOSALS_LOG`):
```
APPROVAL_TIMEOUT_SECONDS = 300
```

Note: `HYBRID_WEIGHT` (line 30) stays — it's the same value as `vault_search_weight` registry default, but the registry is the new authority. `RECENCY_HALF_LIFE_DAYS` (line 31) stays for now — consumers that don't yet use `get_setting()` still need it. The Expert-tier registry entry shadows it for consumers that do use `get_setting()`.

- [ ] **Step 5: Update `core/cognition/complexity.py` — function-level reads**

Replace the import block (lines 17-24):
```python
from core.interface.config import (
    COMPLEXITY_LENGTH_THRESHOLD,
    COMPLEXITY_LENGTH_PENALTY,
    COMPLEXITY_DOMAIN_PENALTY,
    COMPLEXITY_MULTI_DOMAIN_PENALTY,
    COMPLEXITY_CREATIVE_PENALTY,
    COMPLEXITY_SKIP_LOCAL_THRESHOLD,
)
```

With:
```python
from core.interface.config import (
    COMPLEXITY_LENGTH_PENALTY,
    COMPLEXITY_DOMAIN_PENALTY,
    COMPLEXITY_MULTI_DOMAIN_PENALTY,
    COMPLEXITY_CREATIVE_PENALTY,
    POSTURE_THRESHOLDS,
)
```

In `score_complexity()` (line 85+), change the function body to read settings at call time:

Replace line 97-98:
```python
    words = _tokenize_query(query)
    token_count = _count_tokens(query)
```

With:
```python
    from core.interface.settings import get_setting
    words = _tokenize_query(query)
    token_count = _count_tokens(query)
    length_threshold = get_setting("complexity_length_threshold")
```

Replace line 103:
```python
    if token_count >= COMPLEXITY_LENGTH_THRESHOLD:
```
With:
```python
    if token_count >= length_threshold:
```

Replace line 136:
```python
    skip_local = penalty > COMPLEXITY_SKIP_LOCAL_THRESHOLD
```
With:
```python
    posture = get_setting("cloud_routing_posture")
    threshold = POSTURE_THRESHOLDS.get(posture, 20.0)
    skip_local = penalty > threshold
```

- [ ] **Step 6: Update `core/memory/session.py` — function-level read**

Replace line 31:
```python
SESSION_TIMEOUT_MINUTES = 30
```

Remove it entirely.

In `_is_expired()` (line 90+), replace line 102:
```python
    if elapsed_minutes > state.get("timeout_minutes", SESSION_TIMEOUT_MINUTES):
```
With:
```python
    from core.interface.settings import get_setting
    if elapsed_minutes > state.get("timeout_minutes", get_setting("session_timeout")):
```

- [ ] **Step 7: Update `core/autonomic/daemon.py` — function-level read**

In the import block, remove `DAEMON_IDLE_TIMEOUT_MINUTES` from the `config` import list.

In the heartbeat function (around line 104-105), replace:
```python
    threshold = DAEMON_IDLE_TIMEOUT_MINUTES * 60
```
With:
```python
    from core.interface.settings import get_setting
    threshold = get_setting("idle_timeout") * 60
```

- [ ] **Step 8: Run integration tests**

Run: `python -m pytest tests/test_settings_integration.py -v`
Expected: 5 passed

- [ ] **Step 9: Run full test suite to check for regressions**

Run: `python -m pytest tests/ -x -q --timeout=30`
Expected: All tests pass. If any fail due to removed constants, fix the imports.

- [ ] **Step 10: Commit**

```bash
git add core/interface/settings.py core/interface/settings_registry.py core/interface/config.py core/cognition/complexity.py core/memory/session.py core/autonomic/daemon.py tests/test_settings_integration.py
git commit -m "feat: registry-based settings storage + hardcoded value extraction (T-117)"
```

---

## Task 3: API Endpoints — Tier-Structured Response

**Files:**
- Modify: `core/interface/api/routes/settings.py` (lines 1-35)

- [ ] **Step 1: Update the API routes**

Replace `core/interface/api/routes/settings.py`:

```python
"""Settings API — GET/PUT /api/settings."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

log = logging.getLogger(__name__)

router = APIRouter()


class SettingUpdate(BaseModel):
    key: str
    value: object


@router.get("")
def get_settings():
    from core.interface.settings import get_tiered_settings
    return get_tiered_settings()


@router.put("")
def put_setting(body: SettingUpdate):
    from core.interface.settings import update_setting
    try:
        result = update_setting(body.key, body.value)
    except KeyError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except ValueError as e:
        log.warning("[put_setting] invalid setting: %s", e)
        raise HTTPException(status_code=400, detail=str(e))
    return result
```

- [ ] **Step 2: Run existing API tests to check for regressions**

Run: `python -m pytest tests/test_api.py -v -k settings`
Expected: Pass (or no matching tests — the existing test file tests other endpoints)

- [ ] **Step 3: Commit**

```bash
git add core/interface/api/routes/settings.py
git commit -m "feat: tier-structured GET /api/settings + validated PUT (T-117)"
```

---

## Task 4: TUI Settings View — Essential + Advanced Sections

**Files:**
- Modify: `core/interface/tui/views/settings.py` (full rewrite)

- [ ] **Step 1: Rewrite the TUI Settings view**

Replace `core/interface/tui/views/settings.py`:

```python
"""Settings view — Essential, Advanced, and Connections sections."""
from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widget import Widget
from textual.widgets import Button, Input, RadioButton, RadioSet, Static, Switch


class SettingsView(Widget, can_focus=True):
    """Settings screen: essential settings, advanced tuning, provider connections."""

    def compose(self) -> ComposeResult:
        yield Static(
            "\u25c8 Settings",
            id="settings-header",
        )
        with VerticalScroll(id="settings-scroll"):
            # ── Essential ─────────────────────────────────────────
            with Vertical(id="settings-essential"):
                yield Static("essential", classes="section-label")
                yield Static("\u2500" * 35, classes="section-separator")

                yield Static("routing posture", classes="setting-label")
                with RadioSet(id="posture-radio"):
                    yield RadioButton("conservative", id="posture-conservative")
                    yield RadioButton("balanced", id="posture-balanced", value=True)
                    yield RadioButton("aggressive", id="posture-aggressive")
                yield Static("[dim]How aggressively queries route to cloud[/]", classes="setting-hint")

                yield Static("temperature", classes="setting-label")
                yield Input(value="0.7", id="input-temperature", type="number")
                yield Static("[dim]Default generation temperature (0.0-2.0)[/]", classes="setting-hint")

                yield Static("max tokens", classes="setting-label")
                yield Input(value="2048", id="input-max-tokens", type="integer")
                yield Static("[dim]Default max response tokens (256-32768)[/]", classes="setting-hint")

                yield Static("theme", classes="setting-label")
                with Horizontal(id="theme-buttons"):
                    yield Button("Amber", id="btn-theme-amber")
                    yield Button("Green", id="btn-theme-green")
                    yield Button("White", id="btn-theme-white")

                yield Static("idle timeout (minutes)", classes="setting-label")
                yield Input(value="15", id="input-idle-timeout", type="integer")
                yield Static("[dim]Minutes before IDLE cascade (1-120)[/]", classes="setting-hint")

                yield Static("session timeout (minutes)", classes="setting-label")
                yield Input(value="30", id="input-session-timeout", type="integer")
                yield Static("[dim]Minutes before session auto-close (5-180)[/]", classes="setting-hint")

                with Horizontal(classes="setting-toggle"):
                    yield Static("boot quote", classes="setting-label")
                    yield Switch(value=True, id="switch-boot-quote")

                with Horizontal(classes="setting-toggle"):
                    yield Static("notifications", classes="setting-label")
                    yield Switch(value=True, id="switch-notifications")

            # ── Advanced ──────────────────────────────────────────
            with Vertical(id="settings-advanced"):
                yield Static("advanced", classes="section-label")
                yield Static("\u2500" * 35, classes="section-separator")

                yield Static("PII threshold", classes="setting-label")
                yield Input(value="0.3", id="input-pii-threshold", type="number")
                yield Static("[dim]PII detection confidence (0.0-1.0)[/]", classes="setting-hint")

                yield Static("monthly credit cap", classes="setting-label")
                yield Input(value="1000000", id="input-credit-cap", type="number")
                yield Static("[dim]Monthly cloud spending limit[/]", classes="setting-hint")

                yield Static("approval timeout (seconds)", classes="setting-label")
                yield Input(value="300", id="input-approval-timeout", type="integer")
                yield Static("[dim]ASK_FIRST proposal expiry (30-3600)[/]", classes="setting-hint")

                yield Static("vault search weight", classes="setting-label")
                yield Input(value="0.7", id="input-vault-weight", type="number")
                yield Static("[dim]Vector vs BM25 balance (0.0-1.0)[/]", classes="setting-hint")

            # ── Connections ───────────────────────────────────────
            with Vertical(id="settings-providers"):
                yield Static("connections", classes="section-label")
                yield Static("\u2500" * 35, classes="section-separator")
                yield Static("(loading...)", id="provider-list")

            with Vertical(id="settings-claude"):
                yield Static("claude", classes="section-label")
                yield Static("\u2500" * 35, classes="section-separator")
                yield Static("(loading...)", id="claude-status")

            with Vertical(id="settings-google"):
                yield Static("google services", classes="section-label")
                yield Static("\u2500" * 35, classes="section-separator")
                yield Static("(loading...)", id="google-service-list")

    # ── Setting ID → registry key mapping ─────────────────────────
    _INPUT_MAP = {
        "input-temperature": "inference_temperature",
        "input-max-tokens": "inference_max_tokens",
        "input-idle-timeout": "idle_timeout",
        "input-session-timeout": "session_timeout",
        "input-pii-threshold": "pii_confidence_threshold",
        "input-credit-cap": "credits_monthly_cap",
        "input-approval-timeout": "approval_timeout",
        "input-vault-weight": "vault_search_weight",
    }

    _SWITCH_MAP = {
        "switch-boot-quote": "boot_quote",
        "switch-notifications": "notifications",
    }

    _POSTURE_MAP = {
        "posture-conservative": "conservative",
        "posture-balanced": "balanced",
        "posture-aggressive": "aggressive",
    }

    def on_mount(self) -> None:
        """Load current settings from API and update widgets."""
        self.run_worker(self._load_settings())

    async def _load_settings(self) -> None:
        """Fetch current settings and apply to widgets."""
        data = await self.app.api_client.fetch_json("/api/settings")
        if not data:
            return
        # Flatten tiers for easy lookup
        flat: dict[str, object] = {}
        for tier_data in data.values():
            if isinstance(tier_data, dict):
                for key, meta in tier_data.items():
                    if isinstance(meta, dict):
                        flat[key] = meta.get("value", meta)

        # Apply to inputs
        for widget_id, setting_key in self._INPUT_MAP.items():
            if setting_key in flat:
                try:
                    self.query_one(f"#{widget_id}", Input).value = str(flat[setting_key])
                except Exception:
                    pass

        # Apply to switches
        for widget_id, setting_key in self._SWITCH_MAP.items():
            if setting_key in flat:
                try:
                    self.query_one(f"#{widget_id}", Switch).value = bool(flat[setting_key])
                except Exception:
                    pass

        # Apply posture radio
        posture = flat.get("cloud_routing_posture", "balanced")
        for radio_id, posture_val in self._POSTURE_MAP.items():
            try:
                rb = self.query_one(f"#{radio_id}", RadioButton)
                rb.value = (posture_val == posture)
            except Exception:
                pass

    def _save_setting(self, key: str, value: object) -> None:
        """Persist a setting via the API."""
        async def _put():
            result = await self.app.api_client.update_setting(key, value)
            if result.get("restart_required"):
                self.notify("Restart required for this setting to take effect")

        self.run_worker(_put())

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Save numeric/text inputs on Enter."""
        key = self._INPUT_MAP.get(event.input.id, "")
        if not key:
            return
        raw = event.value.strip()
        if not raw:
            return
        try:
            value: object = float(raw) if "." in raw else int(raw)
        except ValueError:
            self.notify(f"Invalid value: {raw}", severity="error")
            return
        self._save_setting(key, value)
        self.notify(f"{key} = {value}")

    def on_radio_set_changed(self, event: RadioSet.Changed) -> None:
        """Save posture on radio change."""
        if event.radio_set.id != "posture-radio":
            return
        pressed = event.pressed
        posture = self._POSTURE_MAP.get(pressed.id, "")
        if posture:
            self._save_setting("cloud_routing_posture", posture)
            self.notify(f"Routing posture: {posture}")

    def on_switch_changed(self, event: Switch.Changed) -> None:
        """Save toggle switches."""
        key = self._SWITCH_MAP.get(event.switch.id, "")
        if not key:
            return
        self._save_setting(key, event.value)
        self.notify(f"{key} = {event.value}")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle theme button clicks."""
        theme_map = {
            "btn-theme-amber": "amber",
            "btn-theme-green": "green",
            "btn-theme-white": "white",
        }
        theme_name = theme_map.get(event.button.id, "")
        if not theme_name:
            return
        self._apply_theme(theme_name)

    def _apply_theme(self, theme_name: str) -> None:
        """Apply theme CSS class and persist via API."""
        self._save_setting("theme", theme_name)
        screen = self.app.screen
        screen.remove_class("theme-amber", "theme-green", "theme-white")
        if theme_name != "amber":
            screen.add_class(f"theme-{theme_name}")
        self.notify(f"Theme: {theme_name}")

    # ── Provider/OAuth update methods (called by app on data load) ──

    def update_providers(self, models: dict) -> None:
        """Update provider list from /api/models response."""
        providers: dict[str, bool] = {}
        for category, model_list in models.items():
            if not isinstance(model_list, list):
                continue
            if category == "local" and model_list:
                providers["local (Ollama)"] = True
            for m in model_list:
                if isinstance(m, dict) and m.get("provider"):
                    name = m["provider"]
                    providers[name] = True
        if providers:
            lines = [f"{name}  \u25cf connected" for name in providers]
        else:
            lines = ["No providers detected"]
        self.query_one("#provider-list", Static).update("\n".join(lines))

    def update_claude(self, claude_status: dict) -> None:
        """Update Claude OAuth status."""
        if claude_status.get("connected"):
            text = "Claude OAuth  \u25cf connected"
        else:
            text = "Claude OAuth  \u25cb not connected"
        self.query_one("#claude-status", Static).update(text)

    def update_google(self, google_status: dict) -> None:
        """Update Google services status."""
        from core.interface.tui.client import scopes_to_services

        if google_status.get("connected"):
            services = scopes_to_services(google_status.get("scopes", []))
            if services:
                lines = [f"{svc}  \u25cf connected" for svc in services]
            else:
                lines = ["connected (no services detected)"]
        else:
            lines = ["not connected \u25cb"]
        self.query_one("#google-service-list", Static).update("\n".join(lines))
```

- [ ] **Step 2: Check the TUI client has `fetch_json` method**

The `_load_settings` method calls `self.app.api_client.fetch_json("/api/settings")`. Verify this method exists on the TUI API client. If it doesn't, use the existing pattern (e.g., how `update_setting` works) and add a simple GET wrapper:

```python
async def fetch_json(self, path: str) -> dict:
    try:
        r = await self._client.get(path)
        if r.status_code == 200:
            return r.json()
    except (httpx.ConnectError, httpx.TimeoutException):
        pass
    return {}
```

- [ ] **Step 3: Run existing TUI tests**

Run: `python -m pytest tests/test_tui/ -v`
Expected: All pass. If any fail due to the new widget structure (e.g., the old `#settings-appearance` ID), fix accordingly.

- [ ] **Step 4: Commit**

```bash
git add core/interface/tui/views/settings.py core/interface/tui/client.py
git commit -m "feat: TUI Settings Essential + Advanced sections (T-117)"
```

---

## Task 5: CLI Config — Registry Integration

**Files:**
- Modify: `core/interface/cli.py:2212-2310` (config command)
- Test: `tests/test_cli_t104.py` (append 4 new tests)

- [ ] **Step 1: Write the CLI config tests**

Append to `tests/test_cli_t104.py`:

```python
# ── T-117: config registry integration ──────────────────────────────

def test_config_bare_shows_tiers(runner, monkeypatch):
    """oikos config bare shows Essential and Advanced headers."""
    _mock_settings(monkeypatch)
    result = runner.invoke(main, ["config"])
    assert result.exit_code == 0
    assert "Essential" in result.output
    assert "Advanced" in result.output


def test_config_write_essential(runner, monkeypatch):
    """oikos config cloud_routing_posture conservative writes successfully."""
    _mock_settings(monkeypatch)
    result = runner.invoke(main, ["config", "cloud_routing_posture", "conservative"])
    assert result.exit_code == 0
    assert "saved" in result.output.lower() or "conservative" in result.output


def test_config_advanced_redirect(runner, monkeypatch):
    """oikos config pii_confidence_threshold 0.8 prints redirect."""
    _mock_settings(monkeypatch)
    result = runner.invoke(main, ["config", "pii_confidence_threshold", "0.8"])
    assert "Advanced" in result.output or "TUI" in result.output


def test_config_expert_direct_write(runner, monkeypatch):
    """oikos config cosine_sensitivity 0.8 writes directly."""
    _mock_settings(monkeypatch)
    result = runner.invoke(main, ["config", "cosine_sensitivity", "0.8"])
    assert result.exit_code == 0
    assert "saved" in result.output.lower() or "0.8" in result.output


def _mock_settings(monkeypatch):
    """Isolate settings for CLI tests."""
    from core.interface.settings_registry import SETTINGS_REGISTRY
    store = {k: v.default for k, v in SETTINGS_REGISTRY.items()}

    def fake_get(key):
        if key in store:
            return store[key]
        raise KeyError(f"Unknown setting: {key}")

    def fake_update(key, value):
        from core.interface.settings_registry import validate_setting
        from core.interface.settings import _coerce
        defn = SETTINGS_REGISTRY[key]
        value = _coerce(value, defn.setting_type)
        ok, msg = validate_setting(key, value)
        if not ok:
            raise ValueError(msg)
        store[key] = value
        return {"applied": True, "restart_required": defn.restart_required}

    def fake_tiered():
        from core.interface.settings_registry import SettingTier
        tiers = {"essential": {}, "advanced": {}, "expert": {}}
        for k, defn in SETTINGS_REGISTRY.items():
            val = store.get(k, defn.default)
            tiers[defn.tier.value][k] = defn.to_api_dict(val)
        return tiers

    monkeypatch.setattr("core.interface.settings.get_setting", fake_get)
    monkeypatch.setattr("core.interface.settings.update_setting", fake_update)
    monkeypatch.setattr("core.interface.settings.get_tiered_settings", fake_tiered)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_cli_t104.py::test_config_bare_shows_tiers -v`
Expected: FAIL — current config command doesn't output "Essential"

- [ ] **Step 3: Rewrite CLI config command**

In `core/interface/cli.py`, replace lines 2212-2310 (from `# ── Task 6: oikos config ──` through end of `config_cmd`):

```python
# ── Task 6: oikos config ────────────────────────────────────────────

CONFIG_REDIRECTS = {
    "default_provider": "oikos provider <name>",
    "cloud_provider": "oikos provider <name>",
}

CONFIG_REDIRECT_PREFIXES = [
    ("provider_", "oikos provider <name>"),
    ("room.", "oikos room edit <name>"),
    ("allowed_providers", "oikos room edit <name>"),
]


@main.command("config")
@click.argument("key", required=False, default=None)
@click.argument("value", required=False, default=None)
def config_cmd(key, value):
    """View or update runtime settings."""
    from core.interface.settings import get_setting, get_tiered_settings, update_setting
    from core.interface.settings_registry import SETTINGS_REGISTRY, SettingTier

    # Bare: show tiered settings
    if key is None:
        tiered = get_tiered_settings()
        tier_labels = {
            "essential": "Essential",
            "advanced": "Advanced [dim](use TUI Settings F5 or API)[/]",
            "expert": "Expert [dim](edit settings.json directly)[/]",
        }
        for tier_name, label in tier_labels.items():
            settings = tiered.get(tier_name, {})
            if not settings:
                continue
            console.print(f"\n  [bold]{label}[/]")
            for skey, meta in sorted(settings.items()):
                val = meta.get("value", "")
                desc = meta.get("description", "")
                console.print(f"    {skey:<30} {str(val):<12} [dim]{desc}[/]")
        console.print()
        return

    # Key only: show single value
    if value is None:
        try:
            val = get_setting(key)
            defn = SETTINGS_REGISTRY.get(key)
            desc = f"  [dim]{defn.description}[/]" if defn else ""
            console.print(f"  {key} = {val}{desc}")
        except KeyError:
            console.print(f"[red]Unknown setting: {key}[/]")
            raise SystemExit(1)
        return

    # Key + value: check redirects
    if key in CONFIG_REDIRECTS:
        console.print(f"[yellow]Use: {CONFIG_REDIRECTS[key]}[/]")
        return

    for prefix, redirect in CONFIG_REDIRECT_PREFIXES:
        if key.startswith(prefix):
            console.print(f"[yellow]Use: {redirect}[/]")
            return

    # Check registry
    if key not in SETTINGS_REGISTRY:
        console.print(f"[red]Unknown setting: {key}. Run 'oikos config' to see available settings.[/]")
        raise SystemExit(1)

    defn = SETTINGS_REGISTRY[key]

    # Advanced tier: redirect to TUI
    if defn.tier == SettingTier.ADVANCED:
        console.print(f"[yellow]Advanced setting. Use TUI Settings (F5) or the API.[/]")
        return

    # Essential + Expert: write directly
    try:
        result = update_setting(key, value)
        console.print(f"  {key} = {value} [green](saved)[/]")
        if result.get("restart_required"):
            console.print("  [yellow]Restart required for this change to take effect.[/]")
    except (ValueError, KeyError) as e:
        console.print(f"[red]{e}[/]")
        raise SystemExit(1)
```

- [ ] **Step 4: Run CLI config tests**

Run: `python -m pytest tests/test_cli_t104.py -v -k config`
Expected: All config tests pass (old + new)

- [ ] **Step 5: Run full test suite**

Run: `python -m pytest tests/ -x -q --timeout=30`
Expected: All pass

- [ ] **Step 6: Commit**

```bash
git add core/interface/cli.py tests/test_cli_t104.py
git commit -m "feat: CLI oikos config registry integration (T-117)"
```

---

## Task 6: Fix Regressions + Final Verification

- [ ] **Step 1: Grep for remaining references to removed constants**

Search for any imports of removed constants that weren't updated in earlier tasks:

```bash
# Search for imports of removed constants
grep -rn "INFERENCE_TEMPERATURE\|INFERENCE_MAX_TOKENS\|PII_CONFIDENCE_THRESHOLD\|CREDITS_MONTHLY_CAP\|CLOUD_ROUTING_POSTURE\|COMPLEXITY_SKIP_LOCAL_THRESHOLD\|COMPLEXITY_LENGTH_THRESHOLD\|DAEMON_IDLE_TIMEOUT_MINUTES\|API_DEFAULT_PORT\|APPROVAL_TIMEOUT_SECONDS\|SCANNER_RESONANCE_THRESHOLD\|ROUTING_COSINE_SENSITIVITY_THRESHOLD" core/ --include="*.py" | grep -v __pycache__ | grep "import"
```

Fix any remaining imports to either:
- Use `get_setting("key_name")` inside the function that needs the value
- Import from a different source if appropriate

- [ ] **Step 2: Run full test suite**

Run: `python -m pytest tests/ -x -q --timeout=30`
Expected: All tests pass

- [ ] **Step 3: Run gauntlet**

Run: `python -m core.interface.cli gauntlet`
Expected: 10/10

- [ ] **Step 4: Fix any failures found in steps 1-3**

If any tests or gauntlet probes fail, fix them. Common failure modes:
- An import of a removed constant in a file not touched by Task 2
- A test that directly imports a removed constant for assertion
- Type mismatch (string from settings.json where int expected — `_coerce` should handle this)

- [ ] **Step 5: Final commit if any fixes were needed**

```bash
git add -u
git commit -m "fix: regression fixes from settings extraction (T-117)"
```
