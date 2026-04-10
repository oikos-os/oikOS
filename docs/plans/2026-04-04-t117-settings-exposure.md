# T-117: Settings Exposure — Design Spec

**Date:** 2026-04-04
**Task:** T-117
**Branch:** `t117-settings-exposure`
**Status:** Design approved, pending implementation

---

## Objective

Organize all user-tunable settings into three tiers (Essential / Advanced / Expert), extract hardcoded values into overridable settings via the existing `get_setting()` mechanism, and ensure Essential-tier settings are available in TUI and CLI. The API serves as the shared backend for all interfaces.

## Scope

- Settings registry (single source of truth for metadata + validation)
- Hardcoded value extraction (function-level reads for hot-reload)
- API endpoints (tier-structured GET, validated PUT)
- TUI Settings view expansion (Essential + Advanced sections)
- CLI `oikos config` expansion (replace T-104 allowlist with registry)

**Excluded:** Web UI settings page (doesn't exist yet), per-Room settings (T-118), new daemon behaviors, settings import/export.

---

## Architecture

### Settings Registry — `core/interface/settings_registry.py`

Single source of truth for setting metadata. Two concerns per setting: serializable metadata (for API/UI) and Python-only validation.

```python
class SettingTier(Enum):
    ESSENTIAL = "essential"
    ADVANCED = "advanced"
    EXPERT = "expert"

@dataclass
class SettingDef:
    key: str
    tier: SettingTier
    setting_type: str          # "int", "float", "bool", "enum"
    default: Any
    description: str
    validator: Callable[[Any], bool]
    error_hint: str
    min_val: float | None = None
    max_val: float | None = None
    options: list[str] | None = None  # For enum type
    restart_required: bool = False

    def to_api_dict(self, current_value: Any) -> dict:
        """Serializable metadata for UI widget construction."""
        # Returns everything except validator
```

Helper functions:
- `get_settings_by_tier(tier)` — filter registry by tier
- `validate_setting(key, value)` — returns `(bool, error_message)`
- `get_registry_default(key)` — returns default from registry

### Registry Contents (21 settings)

#### Essential (8) — TUI + CLI + API

| Key | Type | Default | Description |
|---|---|---|---|
| `cloud_routing_posture` | enum: conservative/balanced/aggressive | `balanced` | How aggressively queries route to cloud |
| `inference_temperature` | float 0.0-2.0 | `0.7` | Default generation temperature |
| `inference_max_tokens` | int 256-32768 | `2048` | Default max response tokens |
| `theme` | enum: amber/green/white | `amber` | Color theme |
| `idle_timeout` | int 1-120 | `15` | Minutes before IDLE cascade |
| `session_timeout` | int 5-180 | `30` | Minutes before session auto-close |
| `boot_quote` | bool | `true` | Show doctrine quote on boot |
| `notifications` | bool | `true` | Enable notifications |

#### Advanced (4) — TUI + API (CLI shows redirect)

| Key | Type | Default | Description |
|---|---|---|---|
| `pii_confidence_threshold` | float 0.0-1.0 | `0.5` | PII detection confidence |
| `credits_monthly_cap` | float 0+ | `100.0` | Monthly cloud spending limit ($) |
| `approval_timeout` | int 30-3600 | `300` | ASK_FIRST proposal expiry (seconds) |
| `vault_search_weight` | float 0.0-1.0 | `0.7` | Vector vs BM25 balance |

#### Expert (9) — settings.json only (documented, no UI)

| Key | Type | Default |
|---|---|---|
| `complexity_length_threshold` | int | `50` |
| `cosine_sensitivity` | float | `0.75` |
| `research_dedup_threshold` | float | `0.85` |
| `browser_rate_limit` | float | `2.0` |
| `recency_half_life` | int | `90` |
| `scanner_resonance` | float | `60.0` |
| `drift_inactivity_days` | int | `3` |
| `api_port` | int 1024-65535 | `8420` |
| `rpg_overlay` | bool | `false` |

#### Never exposed (security invariants)

NEVER_LEAVE patterns, output filter CRITICAL patterns, adversarial input guard patterns, file agent prohibited paths. These are architecture, not settings.

---

## Settings Storage & Hot-Reload

### `core/interface/settings.py` modifications

Fallback chain for `get_setting(key)`:
1. `_overrides` (from `settings.json`) — user's explicit override
2. Registry default (`get_registry_default(key)`) — canonical default
3. `KeyError` if key not in registry

The `config.py` uppercase attribute lookup is removed. Registry becomes the source of defaults.

`update_setting()` validates against registry before writing. Type coercion (string → typed value) happens here. Returns `restart_required` from the `SettingDef`.

### Function-level reads (hot-reload)

All consumers read settings inside the function that uses them, not at module level:

```python
# Before (import-time, dead to hot-reload):
SESSION_TIMEOUT_MINUTES = 30

# After (query-time, hot-reloadable):
def _is_expired(state):
    timeout = get_setting("session_timeout")
    ...
```

### Complexity posture derivation

`COMPLEXITY_SKIP_LOCAL_THRESHOLD` is currently derived at import time from posture. Move derivation into the scoring function:

```python
def score_complexity(content: str) -> ComplexityResult:
    posture = get_setting("cloud_routing_posture")
    threshold = _POSTURE_THRESHOLDS.get(posture, 20.0)
    ...
```

### `restart_required`

Only `api_port` returns `true`. All other settings take effect on next use.

### Files touched for extraction

| File | Change |
|---|---|
| `core/memory/session.py` | `SESSION_TIMEOUT_MINUTES` → `get_setting("session_timeout")` inside `_is_expired()` |
| `core/cognition/complexity.py` | Posture threshold derivation inside scoring function |
| `core/autonomic/daemon.py` | Idle timeout read inside function |
| `core/interface/config.py` | Extracted constants removed (consumers switch to `get_setting()`). Posture thresholds map stays for derivation. Non-extracted constants unchanged. |

---

## API Endpoints

### `GET /api/settings`

Returns tier-structured metadata with current effective values:

```json
{
  "essential": {
    "cloud_routing_posture": {
      "value": "balanced",
      "type": "enum",
      "options": ["conservative", "balanced", "aggressive"],
      "description": "How aggressively queries route to cloud",
      "restart_required": false
    },
    "inference_temperature": {
      "value": 0.7,
      "type": "float",
      "min": 0.0,
      "max": 2.0,
      "description": "Default generation temperature",
      "restart_required": false
    }
  },
  "advanced": { "..." : "..." },
  "expert": { "..." : "..." }
}
```

### `PUT /api/settings`

Request: `{"key": "...", "value": ...}`

Response: `{"applied": true, "restart_required": false}`

Validation failure: 400 + `{"detail": "<error_hint from registry>"}`

Unknown key: 400 + `{"detail": "Unknown setting '<key>'. Run 'oikos config' to see available settings."}`

---

## CLI — `oikos config` Expansion

### Replace T-104 allowlist

Delete `CONFIG_WRITABLE` dict (5 hardcoded keys). Replace with registry filter.

### `oikos config` (bare) — tiered display

```
Essential:
  cloud_routing_posture   balanced     How aggressively queries route to cloud
  inference_temperature   0.7          Default generation temperature
  inference_max_tokens    2048         Default max response tokens
  theme                   amber        Color theme
  idle_timeout            15           Minutes before IDLE cascade
  session_timeout         30           Minutes before session auto-close
  boot_quote              true         Show doctrine quote on boot
  notifications           true         Enable notifications

Advanced (use TUI Settings F5 or API):
  pii_confidence_threshold  0.5        PII detection confidence
  credits_monthly_cap       100.00     Monthly cloud spending limit
  approval_timeout          300        ASK_FIRST proposal expiry (seconds)
  vault_search_weight       0.7        Vector vs BM25 balance

Expert (edit settings.json directly):
  complexity_length_threshold  50      Length threshold for complexity scoring
  cosine_sensitivity           0.75    Sovereign query detection threshold
  ...
```

### Write rules by tier

- **Essential** — writes directly via `update_setting()`
- **Advanced** — prints: `"Advanced setting. Use TUI Settings (F5) or the API."`
- **Expert** — writes directly
- **Unknown** — `"Unknown setting. Run 'oikos config' to see available settings."`

### Existing redirects preserved

`default_provider` → `oikos provider <name>`, `room.*` → `oikos room edit <name>`. Unchanged.

### Read (any tier)

`oikos config <key>` shows value + description for any tier.

---

## TUI Settings View

### `core/interface/tui/views/settings.py` — new layout

**Section 1: Essential**
- Routing posture — `RadioSet` (conservative / balanced / aggressive)
- Temperature — `Input` (float, 0.0-2.0)
- Max tokens — `Input` (int, 256-32768)
- Theme — existing 3 buttons (moved from Appearance)
- Idle timeout — `Input` (int, 1-120)
- Session timeout — `Input` (int, 5-180)
- Boot quote — `Switch`
- Notifications — `Switch`

**Section 2: Advanced**
- PII threshold — `Input` (float, 0.0-1.0)
- Credit cap — `Input` (float, 0+)
- Approval timeout — `Input` (int, 30-3600)
- Vault search weight — `Input` (float, 0.0-1.0)

**Section 3: Connections** (existing, reorganized)
- Providers
- Claude OAuth
- Google Services

Each setting: label + input widget + dim description hint. Changes save immediately via `PUT /api/settings`. Validation errors show as Toast. Vertical scroll for content overflow.

---

## Testing

### `tests/test_settings_registry.py` (8 tests)

| # | Test |
|---|---|
| 1 | `test_all_settings_have_validators` |
| 2 | `test_essential_tier_count` |
| 3 | `test_validate_routing_posture_valid` |
| 4 | `test_validate_routing_posture_invalid` |
| 5 | `test_validate_temperature_range` |
| 6 | `test_validate_max_tokens_range` |
| 7 | `test_validate_timeout_range` |
| 8 | `test_get_settings_by_tier` |

### `tests/test_settings_integration.py` (5 tests)

| # | Test |
|---|---|
| 9 | `test_setting_write_roundtrip` |
| 10 | `test_setting_defaults_match_registry` |
| 11 | `test_setting_affects_behavior` |
| 12 | `test_invalid_setting_rejected` |
| 13 | `test_unknown_setting_rejected` |

### CLI tests (4 tests)

| # | Test |
|---|---|
| 14 | `test_config_bare_shows_tiers` |
| 15 | `test_config_write_essential` |
| 16 | `test_config_advanced_redirect` |
| 17 | `test_config_expert_direct_write` |

**Total: 17 new tests.**

---

## Verification Criteria

| # | Criterion | Interface |
|---|---|---|
| 1 | Essential settings readable/writable from CLI | CLI |
| 2 | `oikos config` bare shows tiered display | CLI |
| 3 | Advanced-tier CLI write prints redirect | CLI |
| 4 | Expert-tier CLI write succeeds | CLI |
| 5 | All Essential settings visible in TUI Settings | TUI |
| 6 | All Advanced settings visible in TUI Settings | TUI |
| 7 | TUI changes persist via API | TUI |
| 8 | `GET /api/settings` returns tier-structured metadata | API |
| 9 | `PUT /api/settings` validates + returns `restart_required` | API |
| 10 | Changing temperature via API affects next query | API |
| 11 | Changing routing posture affects next query's routing | API |
| 12 | Invalid values produce friendly error with hint | All |
| 13 | All existing tests pass | All |
| 14 | 17+ new tests passing | Tests |

---

## Commit Plan

### Commit 1: `feat: settings registry + hardcoded value extraction`

| File | Action |
|---|---|
| `core/interface/settings_registry.py` | CREATE |
| `core/interface/settings.py` | MODIFY |
| `core/interface/config.py` | MODIFY |
| `core/memory/session.py` | MODIFY |
| `core/cognition/complexity.py` | MODIFY |
| `core/autonomic/daemon.py` | MODIFY |
| `core/interface/api/routes/settings.py` | MODIFY |
| `tests/test_settings_registry.py` | CREATE |
| `tests/test_settings_integration.py` | CREATE |

### Commit 2: `feat: TUI Settings Essential + Advanced sections`

| File | Action |
|---|---|
| `core/interface/tui/views/settings.py` | MODIFY |
| TUI tests | MODIFY/CREATE |

### Commit 3: `feat: CLI oikos config registry integration`

| File | Action |
|---|---|
| `core/interface/cli.py` | MODIFY |
| CLI tests | CREATE/MODIFY |

---

## Dependencies

- **T-104 (CLI Completion):** Merged. `oikos config` infrastructure exists. T-117 extends it.
- **T-116 (Routing Transparency):** Merged. No conflict.

## Naming Decision

Dispatch used `local/balanced/cloud`. Codebase uses `conservative/balanced/aggressive`. SYNTH ruled: keep codebase names — they describe posture toward cloud routing thresholds, not destinations.
