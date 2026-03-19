"""Tests for provider bootstrap — startup registration."""

from unittest.mock import patch

import pytest

from core.cognition.providers.bootstrap import create_registry
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
    with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key", "GEMINI_API_KEY": ""}):
        reg = create_registry()
        assert "claude" in reg.list_all()


def test_create_registry_no_claude_without_key():
    with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "", "GEMINI_API_KEY": ""}, clear=False):
        import os
        os.environ.pop("ANTHROPIC_API_KEY", None)
        reg = create_registry()
        assert "claude" not in reg.list_all()


def test_create_registry_has_gemini_if_key():
    with patch.dict("os.environ", {"GEMINI_API_KEY": "test-key", "ANTHROPIC_API_KEY": ""}):
        reg = create_registry()
        assert "gemini" in reg.list_all()


def test_create_registry_default_is_local():
    with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "key", "GEMINI_API_KEY": "key"}):
        reg = create_registry()
        default = reg.get_default()
        assert default.provider_name == "ollama"
