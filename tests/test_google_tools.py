"""Tests for Google MCP tool registration, privacy, and autonomy."""
from __future__ import annotations

import importlib
from unittest.mock import patch

import pytest

from core.framework import clear_registry, get_registered_tools
from core.framework.decorator import PrivacyTier, AutonomyLevel


@pytest.fixture(autouse=True)
def fresh_registry():
    clear_registry()
    import core.framework.tools.google_tools
    importlib.reload(core.framework.tools.google_tools)  # re-trigger registration
    yield
    clear_registry()


def _get_google_tools() -> dict:
    """Return only google toolset tools."""
    return {
        name: (fn, meta)
        for name, (fn, meta) in get_registered_tools().items()
        if meta.toolset == "google"
    }


class TestGoogleToolRegistration:
    def test_eight_tools_registered(self):
        tools = _get_google_tools()
        assert len(tools) == 8, f"Expected 8 google tools, got {len(tools)}: {list(tools.keys())}"

    def test_tool_names(self):
        tools = _get_google_tools()
        expected = {
            "oikos_google_gmail_list",
            "oikos_google_gmail_read",
            "oikos_google_gmail_send",
            "oikos_google_calendar_list",
            "oikos_google_calendar_create",
            "oikos_google_drive_list",
            "oikos_google_drive_read",
            "oikos_google_drive_download",
        }
        assert set(tools.keys()) == expected


class TestGoogleToolPrivacy:
    def test_all_tools_sensitive(self):
        for name, (fn, meta) in _get_google_tools().items():
            assert meta.privacy == PrivacyTier.SENSITIVE, f"{name} should be SENSITIVE"


class TestGoogleToolAutonomy:
    def test_read_tools_are_safe(self):
        safe_tools = {
            "oikos_google_gmail_list", "oikos_google_gmail_read",
            "oikos_google_calendar_list",
            "oikos_google_drive_list", "oikos_google_drive_read",
        }
        for name, (fn, meta) in _get_google_tools().items():
            if name in safe_tools:
                assert meta.autonomy == AutonomyLevel.SAFE, f"{name} should be SAFE"

    def test_write_tools_are_ask_first(self):
        ask_first_tools = {
            "oikos_google_gmail_send",
            "oikos_google_calendar_create",
            "oikos_google_drive_download",
        }
        for name, (fn, meta) in _get_google_tools().items():
            if name in ask_first_tools:
                assert meta.autonomy == AutonomyLevel.ASK_FIRST, f"{name} should be ASK_FIRST"


class TestGoogleToolBehavior:
    def test_gmail_list_raises_when_disconnected(self):
        with patch("core.auth.google_oauth.is_google_connected", return_value=False):
            tools = _get_google_tools()
            fn = tools["oikos_google_gmail_list"][0]
            with pytest.raises(RuntimeError, match="Google not connected"):
                fn()

    def test_gmail_list_calls_client(self):
        with (
            patch("core.auth.google_oauth.is_google_connected", return_value=True),
            patch("core.auth.gmail_client.GmailClient.list_messages", return_value={"messages": []}) as mock_list,
        ):
            tools = _get_google_tools()
            fn = tools["oikos_google_gmail_list"][0]
            result = fn(query="test", max_results=5)
            mock_list.assert_called_once()
            assert result == {"messages": []}

    def test_calendar_create_calls_client(self):
        with (
            patch("core.auth.google_oauth.is_google_connected", return_value=True),
            patch("core.auth.calendar_client.CalendarClient.create_event", return_value={"id": "evt"}) as mock_create,
        ):
            tools = _get_google_tools()
            fn = tools["oikos_google_calendar_create"][0]
            result = fn(summary="Test", start="2026-03-25T10:00:00", end="2026-03-25T11:00:00")
            mock_create.assert_called_once()

    def test_drive_download_calls_client(self):
        with (
            patch("core.auth.google_oauth.is_google_connected", return_value=True),
            patch("core.auth.drive_client.DriveClient.download_file", return_value={"path": "staging/f.txt"}) as mock_dl,
        ):
            tools = _get_google_tools()
            fn = tools["oikos_google_drive_download"][0]
            result = fn(file_id="abc123")
            mock_dl.assert_called_once_with("abc123")


class TestGoogleToolsetFlag:
    def test_google_in_all_toolsets(self):
        from core.framework.toolsets import ALL_TOOLSETS
        assert "google" in ALL_TOOLSETS

    def test_get_tools_by_toolset_google(self):
        from core.framework.toolsets import get_tools_by_toolset
        tools = get_tools_by_toolset("google")
        assert len(tools) == 8
