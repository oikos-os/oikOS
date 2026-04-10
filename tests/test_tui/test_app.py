"""Tests for the OikOSApp shell — navigation, bindings, lifecycle."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.interface.tui.app import OikOSApp
from core.interface.tui.views.lobby import LobbyView
from core.interface.tui.widgets.sidebar import OikOSSidebar


@pytest.fixture
def patched_app():
    """OikOSApp with mocked API client (no real server needed)."""
    mock_client = AsyncMock()
    mock_client.is_reachable.return_value = True
    mock_client.state.return_value = {"fsm_state": "active", "uptime": 100, "version": "2.0.0", "model": "qwen2.5:14b"}
    mock_client.active_room.return_value = {"id": "home", "name": "Home"}
    mock_client.rooms.return_value = [{"id": "home", "name": "Home"}]
    mock_client.vault_stats.return_value = {"unique_files": 42, "total_rows": 200}
    mock_client.models.return_value = {"local": [{"id": "qwen2.5:14b"}]}
    mock_client.settings.return_value = {"theme": "amber"}
    mock_client.claude_status.return_value = {"connected": False}
    mock_client.google_status.return_value = {"connected": False}
    mock_client.events.return_value = []
    mock_client.tools.return_value = {"total": 50, "toolsets": {"vault": ["a", "b"]}}
    mock_client.close.return_value = None

    with patch("core.interface.tui.app.OikOSClient", return_value=mock_client):
        yield OikOSApp()


@pytest.mark.asyncio
async def test_app_starts_on_lobby(patched_app):
    async with patched_app.run_test(size=(120, 40)) as pilot:
        switcher = patched_app.query_one("#content-switcher")
        assert switcher.current == "lobby"


@pytest.mark.asyncio
async def test_f2_switches_to_chat(patched_app):
    async with patched_app.run_test(size=(120, 40)) as pilot:
        await pilot.press("f2")
        switcher = patched_app.query_one("#content-switcher")
        assert switcher.current == "chat"


@pytest.mark.asyncio
async def test_f1_returns_to_lobby(patched_app):
    async with patched_app.run_test(size=(120, 40)) as pilot:
        await pilot.press("f2")  # go to chat
        await pilot.press("f1")  # back to lobby
        switcher = patched_app.query_one("#content-switcher")
        assert switcher.current == "lobby"


@pytest.mark.asyncio
async def test_ctrl_b_toggles_sidebar(patched_app):
    async with patched_app.run_test(size=(120, 40)) as pilot:
        sidebar = patched_app.query_one(OikOSSidebar)
        assert not sidebar.collapsed
        await pilot.press("ctrl+b")
        assert sidebar.collapsed
        await pilot.press("ctrl+b")
        assert not sidebar.collapsed


@pytest.mark.asyncio
async def test_all_views_exist(patched_app):
    async with patched_app.run_test(size=(120, 40)) as pilot:
        # All 7 views should be in the DOM
        assert patched_app.query_one("#lobby") is not None
        assert patched_app.query_one("#chat") is not None
        assert patched_app.query_one("#vault") is not None
        assert patched_app.query_one("#rooms") is not None
        assert patched_app.query_one("#settings") is not None
        assert patched_app.query_one("#tasks") is not None
        assert patched_app.query_one("#agents") is not None


def test_boot_splash_renders():
    """Boot splash prints logo and sleeps."""
    from core.interface.tui.app import run_tui_boot_splash

    with patch("core.interface.tui.app.Console") as MockConsole, \
         patch("core.interface.tui.app.time") as mock_time:
        mock_console = MagicMock()
        MockConsole.return_value = mock_console
        run_tui_boot_splash()
        assert mock_console.print.called
        mock_time.sleep.assert_called_with(2)


def test_no_button_handler():
    """OikOSApp should not have on_button_pressed (lobby has no buttons)."""
    assert not hasattr(OikOSApp, "on_button_pressed")
