"""Shared fixtures for TUI tests."""
from __future__ import annotations

import pytest


@pytest.fixture
def mock_api_responses():
    """Canned API response data for tests."""
    return {
        "/api/health": {"status": "ok"},
        "/api/state": {
            "fsm_state": "active",
            "model": "qwen2.5:14b",
            "uptime": 3600.0,
            "version": "0.0.8",
        },
        "/api/rooms": [
            {"id": "home", "name": "Home"},
            {"id": "research", "name": "Research"},
        ],
        "/api/rooms/active": {"id": "home", "name": "Home"},
        "/api/models": {
            "local": [{"id": "qwen2.5:14b", "name": "qwen2.5:14b"}],
            "cloud": [{"id": "gemini-2.5-pro", "name": "gemini-2.5-pro"}],
        },
        "/api/vault/stats": {"total_rows": 300, "unique_files": 132},
        "/api/settings": {"theme": "amber", "inference_model": "qwen2.5:14b"},
        "/api/auth/claude/status": {"connected": True},
        "/api/auth/google/status": {"connected": True, "services": ["gmail", "calendar", "drive"]},
        "/api/events": [
            {"timestamp": "2026-03-23T14:32:00", "type": "chat", "summary": "12 messages in home"},
        ],
    }
