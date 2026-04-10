"""Settings registry — single source of truth for setting metadata and validation.

Three tiers:
  - Essential: TUI + CLI + API (user-facing knobs)
  - Advanced: TUI + API (power-user tuning)
  - Expert: settings.json only (codebase-level)
"""

from __future__ import annotations

from dataclasses import dataclass
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
    "notifications_must_enabled": SettingDef(
        key="notifications_must_enabled",
        tier=SettingTier.ADVANCED,
        setting_type="bool",
        default=True,
        description="Surface MUST-tier notifications (safety, budget, session warnings)",
        validator=lambda v: isinstance(v, bool),
        error_hint="Must be true or false",
    ),
    "notifications_should_enabled": SettingDef(
        key="notifications_should_enabled",
        tier=SettingTier.ADVANCED,
        setting_type="bool",
        default=True,
        description="Surface SHOULD-tier notifications (idle cascade, restarts, budget alerts)",
        validator=lambda v: isinstance(v, bool),
        error_hint="Must be true or false",
    ),
    "notifications_desktop_enabled": SettingDef(
        key="notifications_desktop_enabled",
        tier=SettingTier.ADVANCED,
        setting_type="bool",
        default=True,
        description="Escalate CRITICAL notifications to Windows desktop toast",
        validator=lambda v: isinstance(v, bool),
        error_hint="Must be true or false",
    ),
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
        description="Monthly cloud spending limit (token credits)",
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
