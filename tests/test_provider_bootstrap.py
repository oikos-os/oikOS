"""Tests for provider bootstrap — startup registration."""

from unittest.mock import patch

import pytest

from core.cognition.providers.bootstrap import create_registry
from core.cognition.providers.config_loader import ConfigError
from core.cognition.providers.registry import ProviderRegistry


def test_create_registry_returns_registry():
    with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "", "GEMINI_API_KEY": ""}):
        reg = create_registry()
        assert isinstance(reg, ProviderRegistry)


def test_create_registry_always_has_local():
    with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "", "GEMINI_API_KEY": ""}):
        reg = create_registry()
        assert "local" in reg.list_all()


def test_create_registry_has_claude_if_key():
    with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key", "GEMINI_API_KEY": ""}), \
         patch("core.cognition.providers.bootstrap._try_register_oauth"), \
         patch("core.cognition.providers.bootstrap.load_providers_config",
               side_effect=ConfigError("force env fallback")):
        reg = create_registry()
        assert "claude" in reg.list_all()


def test_create_registry_no_claude_without_key():
    with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "", "GEMINI_API_KEY": ""}, clear=False):
        import os
        os.environ.pop("ANTHROPIC_API_KEY", None)
        reg = create_registry()
        assert "claude" not in reg.list_all()


def test_create_registry_has_gemini_if_key():
    with patch.dict("os.environ", {"GEMINI_API_KEY": "test-key", "ANTHROPIC_API_KEY": ""}), \
         patch("core.cognition.providers.bootstrap._try_register_oauth"), \
         patch("core.cognition.providers.bootstrap.load_providers_config",
               side_effect=ConfigError("force env fallback")):
        reg = create_registry()
        assert "gemini" in reg.list_all()


def test_create_registry_default_is_local():
    config = {
        "general": {"default": "local", "posture": "balanced", "fallback": "local"},
        "providers": {"local": {"type": "ollama", "base_url": "http://localhost:11434", "default_model": "qwen2.5:14b"}},
        "model_tiers": {"simple": "qwen2.5:7b", "moderate": "qwen2.5:14b", "complex": "gemini-2.5-pro"},
        "costs": {"local": {"input": 0.0, "output": 0.0}},
    }
    with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "key", "GEMINI_API_KEY": "key"}), \
         patch("core.cognition.providers.bootstrap.load_providers_config", return_value=config):
        reg = create_registry()
        default = reg.get_default()
        assert default.provider_name == "ollama"


# ── T-120b: Conditional local registration ─────────────────────────


def test_no_local_in_config_skips_ollama():
    """T-120b: When providers.toml has no [providers.local], Ollama is not registered."""
    config = {
        "general": {"default": "gemini", "posture": "balanced"},
        "providers": {
            "gemini": {"type": "gemini"},
        },
        "costs": {},
    }
    with patch.dict("os.environ", {"GEMINI_API_KEY": "test-key"}), \
         patch("core.cognition.providers.bootstrap.load_providers_config", return_value=config), \
         patch("core.cognition.providers.bootstrap._try_register_oauth"):
        reg = create_registry()
        assert "local" not in reg.list_all()
        assert "gemini" in reg.list_all()


def test_local_in_config_registers_ollama():
    """T-120b: When providers.toml has [providers.local], Ollama is registered."""
    config = {
        "general": {"default": "local", "posture": "balanced"},
        "providers": {
            "local": {"type": "ollama", "base_url": "http://localhost:11434", "default_model": "qwen2.5:14b"},
        },
        "costs": {},
    }
    with patch.dict("os.environ", {}), \
         patch("core.cognition.providers.bootstrap.load_providers_config", return_value=config), \
         patch("core.cognition.providers.bootstrap._try_register_oauth"):
        reg = create_registry()
        assert "local" in reg.list_all()
