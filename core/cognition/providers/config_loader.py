"""Provider configuration loader — reads providers.toml for provider setup.

Uses tomllib (Python 3.12 stdlib). Falls back to env-based defaults
if no providers.toml exists, preserving backward compatibility.
"""

from __future__ import annotations

import logging
import tomllib
from pathlib import Path
from typing import Any

from core.interface.config import (
    INFERENCE_MODEL,
    INFERENCE_TIMEOUT_SECONDS,
    PROJECT_ROOT,
    PROVIDER_OLLAMA_BASE_URL,
)

log = logging.getLogger(__name__)

PROVIDERS_TOML_PATH = PROJECT_ROOT / "providers.toml"
VALID_TYPES = {"ollama", "anthropic", "gemini", "openai", "openai-local", "litellm"}
VALID_POSTURES = {"conservative", "balanced", "aggressive"}


class ConfigError(Exception):
    """Invalid or malformed provider configuration."""


def _default_config() -> dict[str, Any]:
    """Return the env-based default config (backward compat with pre-TOML bootstrap).

    Includes all known provider types. Bootstrap filters by env key presence.
    """
    return {
        "general": {
            "default": "local",
            "posture": "balanced",
            "fallback": "local",
        },
        "providers": {
            "local": {
                "type": "ollama",
                "base_url": PROVIDER_OLLAMA_BASE_URL,
                "default_model": INFERENCE_MODEL,
                "timeout": INFERENCE_TIMEOUT_SECONDS,
            },
            "claude": {
                "type": "anthropic",
                "default_model": "claude-sonnet-4-20250514",
                "max_tokens": 4096,
            },
            "gemini": {
                "type": "gemini",
                "default_model": "gemini-2.5-pro",
            },
            "openai": {
                "type": "openai",
                "default_model": "gpt-4o",
                "max_tokens": 4096,
            },
            "litellm": {
                "type": "litellm",
                "default_model": "gpt-4o",
            },
        },
        "model_tiers": {
            "simple": "qwen2.5:7b",
            "moderate": INFERENCE_MODEL,
            "complex": "gemini-2.5-pro",
        },
        "costs": {
            "local": {"input": 0.0, "output": 0.0},
            "claude": {"input": 3.0, "output": 15.0},
            "gemini": {"input": 1.25, "output": 5.0},
            "openai": {"input": 2.5, "output": 10.0},
            "litellm": {"input": 2.5, "output": 10.0},
        },
    }


def load_providers_config(path: Path | None = None) -> dict[str, Any]:
    """Load provider config from TOML file, falling back to defaults.

    Args:
        path: Path to providers.toml. Defaults to PROJECT_ROOT/providers.toml.

    Returns:
        Parsed config dict with keys: general, providers, model_tiers, costs.

    Raises:
        ConfigError: If the TOML exists but is invalid.
    """
    path = path or PROVIDERS_TOML_PATH

    if not path.exists():
        log.info("No providers.toml found at %s — using env-based defaults", path)
        return _default_config()

    try:
        raw = path.read_bytes()
        config = tomllib.loads(raw.decode("utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"Malformed providers.toml: {exc}") from exc

    _validate(config)

    # Merge defaults for missing optional sections
    defaults = _default_config()
    config.setdefault("general", defaults["general"])
    config["general"].setdefault("fallback", "local")
    config.setdefault("model_tiers", defaults["model_tiers"])
    config.setdefault("costs", defaults["costs"])
    config.setdefault("providers", defaults["providers"])

    log.info("Loaded providers.toml: %d providers, default=%s",
             len(config.get("providers", {})), config["general"].get("default"))
    return config


def _validate(config: dict) -> None:
    """Validate provider config structure."""
    general = config.get("general", {})
    providers = config.get("providers", {})

    # Validate posture
    posture = general.get("posture", "balanced")
    if posture not in VALID_POSTURES:
        raise ConfigError(
            f"Invalid posture '{posture}' — must be one of: {', '.join(sorted(VALID_POSTURES))}"
        )

    # Validate provider types
    for name, prov in providers.items():
        ptype = prov.get("type")
        if ptype is None:
            raise ConfigError(f"Provider '{name}' missing required 'type' field")
        if ptype not in VALID_TYPES:
            raise ConfigError(
                f"Provider '{name}' has invalid type '{ptype}' — must be one of: {', '.join(sorted(VALID_TYPES))}"
            )

    # Validate default references a defined provider
    default = general.get("default", "local")
    if default not in providers and providers:
        raise ConfigError(
            f"Default provider '{default}' not defined in [providers.*] — "
            f"available: {', '.join(sorted(providers.keys()))}"
        )


def generate_default_config(path: Path | None = None) -> Path:
    """Write a commented default providers.toml if none exists.

    Returns:
        Path to the generated (or existing) config file.
    """
    path = path or PROVIDERS_TOML_PATH

    if path.exists():
        log.info("providers.toml already exists at %s", path)
        return path

    example = PROJECT_ROOT / "providers.toml.example"
    if example.exists():
        path.write_text(example.read_text(encoding="utf-8"), encoding="utf-8")
    else:
        path.write_text(_DEFAULT_TOML, encoding="utf-8")

    log.info("Generated default providers.toml at %s", path)
    return path


_DEFAULT_TOML = """\
# oikOS Provider Configuration
# API keys are NEVER stored here — use environment variables or .env file.

[general]
default = "local"
posture = "balanced"
fallback = "local"

[providers.local]
type = "ollama"
base_url = "http://localhost:11434"
default_model = "qwen2.5:14b"
timeout = 60

# [providers.claude]
# type = "anthropic"
# default_model = "claude-sonnet-4-20250514"
# max_tokens = 4096

# [providers.openai]
# type = "openai"
# default_model = "gpt-4o"
# max_tokens = 4096

[model_tiers]
simple = "qwen2.5:7b"
moderate = "qwen2.5:14b"
complex = "gemini-2.5-pro"

[costs.local]
input = 0.0
output = 0.0
"""
