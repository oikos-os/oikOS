"""Tests for TUI-4 screens: Rooms, Settings, Tasks, Agents."""
from __future__ import annotations

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Button, ListView, Static

from core.interface.tui.views.agents import AgentsView
from core.interface.tui.views.rooms import RoomsView
from core.interface.tui.views.settings import SettingsView
from core.interface.tui.views.tasks import TasksView


# ---------------------------------------------------------------------------
# Test harnesses — minimal App wrapping each view
# ---------------------------------------------------------------------------

class RoomsTestApp(App):
    def compose(self) -> ComposeResult:
        yield RoomsView(id="rooms")


class SettingsTestApp(App):
    def compose(self) -> ComposeResult:
        yield SettingsView(id="settings")


class TasksTestApp(App):
    def compose(self) -> ComposeResult:
        yield TasksView(id="tasks")


class AgentsTestApp(App):
    def compose(self) -> ComposeResult:
        yield AgentsView(id="agents")


# ---------------------------------------------------------------------------
# Sample data
# ---------------------------------------------------------------------------

SAMPLE_ROOMS = [
    {
        "id": "home",
        "name": "Home",
        "description": "Default room",
        "model": {"provider": None, "model": None},
        "allowed_providers": None,
        "toolsets": None,
        "vault_scope": {"mode": "all", "paths": [], "tags": []},
        "autonomy": {"overrides": {}},
    },
    {
        "id": "research",
        "name": "Research",
        "description": "Deep research room",
        "model": {"provider": "gemini", "model": "gemini-2.5-pro"},
        "allowed_providers": ["local", "gemini"],
        "toolsets": ["vault", "browser", "research"],
        "vault_scope": {"mode": "include", "paths": [], "tags": ["research"]},
        "autonomy": {"overrides": {"browser.navigate": "ASK_FIRST"}},
    },
]

SAMPLE_MODELS = {
    "local": [{"id": "qwen2.5:14b", "name": "qwen2.5:14b"}],
    "cloud": [{"id": "gemini-2.5-pro", "name": "gemini-2.5-pro", "provider": "gemini"}],
}


# ---------------------------------------------------------------------------
# ROOMS TESTS
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_rooms_composes():
    """RoomsView mounts without error."""
    app = RoomsTestApp()
    async with app.run_test(size=(120, 40)):
        view = app.query_one(RoomsView)
        assert view is not None


@pytest.mark.asyncio
async def test_rooms_has_list():
    """RoomsView contains a ListView for rooms."""
    app = RoomsTestApp()
    async with app.run_test(size=(120, 40)):
        lv = app.query_one("#rooms-list", ListView)
        assert lv is not None


@pytest.mark.asyncio
async def test_rooms_has_config_panel():
    """RoomsView contains the config detail panel."""
    app = RoomsTestApp()
    async with app.run_test(size=(120, 40)):
        detail = app.query_one("#room-config-detail", Static)
        assert detail is not None


@pytest.mark.asyncio
async def test_rooms_update_populates_list():
    """update_rooms populates the ListView with room entries."""
    app = RoomsTestApp()
    async with app.run_test(size=(120, 40)) as pilot:
        view = app.query_one(RoomsView)
        view.update_rooms(SAMPLE_ROOMS, active_id="home")
        await pilot.pause()
        lv = app.query_one("#rooms-list", ListView)
        assert len(lv.children) == 2


@pytest.mark.asyncio
async def test_rooms_shows_config_on_update():
    """update_rooms shows the first room's config by default."""
    app = RoomsTestApp()
    async with app.run_test(size=(120, 40)) as pilot:
        view = app.query_one(RoomsView)
        view.update_rooms(SAMPLE_ROOMS, active_id="home")
        await pilot.pause()
        text = str(app.query_one("#room-config-detail", Static).render())
        assert "Home" in text
        assert "active" in text


@pytest.mark.asyncio
async def test_rooms_header_update():
    """_update_header sets the room count."""
    app = RoomsTestApp()
    async with app.run_test(size=(120, 40)) as pilot:
        view = app.query_one(RoomsView)
        view._rooms = SAMPLE_ROOMS
        view._update_header()
        await pilot.pause()
        text = str(app.query_one("#rooms-header", Static).render())
        assert "2" in text


# ---------------------------------------------------------------------------
# SETTINGS TESTS
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_settings_composes():
    """SettingsView mounts without error."""
    app = SettingsTestApp()
    async with app.run_test(size=(120, 40)):
        view = app.query_one(SettingsView)
        assert view is not None


@pytest.mark.asyncio
async def test_settings_has_providers():
    """SettingsView contains the provider list."""
    app = SettingsTestApp()
    async with app.run_test(size=(120, 40)):
        panel = app.query_one("#provider-list", Static)
        assert panel is not None


@pytest.mark.asyncio
async def test_settings_has_theme_buttons():
    """SettingsView contains theme buttons."""
    app = SettingsTestApp()
    async with app.run_test(size=(120, 40)):
        amber = app.query_one("#btn-theme-amber", Button)
        green = app.query_one("#btn-theme-green", Button)
        white = app.query_one("#btn-theme-white", Button)
        assert amber is not None
        assert green is not None
        assert white is not None


@pytest.mark.asyncio
async def test_settings_update_providers():
    """update_providers populates the provider list."""
    app = SettingsTestApp()
    async with app.run_test(size=(120, 40)) as pilot:
        view = app.query_one(SettingsView)
        view.update_providers(SAMPLE_MODELS)
        await pilot.pause()
        text = str(app.query_one("#provider-list", Static).render())
        assert "local" in text
        assert "connected" in text


@pytest.mark.asyncio
async def test_settings_update_claude():
    """update_claude shows connected status."""
    app = SettingsTestApp()
    async with app.run_test(size=(120, 40)) as pilot:
        view = app.query_one(SettingsView)
        view.update_claude({"connected": True})
        await pilot.pause()
        text = str(app.query_one("#claude-status", Static).render())
        assert "connected" in text


@pytest.mark.asyncio
async def test_settings_update_google():
    """update_google shows service status."""
    app = SettingsTestApp()
    async with app.run_test(size=(120, 40)) as pilot:
        view = app.query_one(SettingsView)
        view.update_google({
            "connected": True,
            "scopes": [
                "https://www.googleapis.com/auth/gmail.readonly",
                "https://www.googleapis.com/auth/calendar",
            ],
        })
        await pilot.pause()
        text = str(app.query_one("#google-service-list", Static).render())
        assert "Gmail" in text
        assert "Calendar" in text


# ---------------------------------------------------------------------------
# TASKS TESTS
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_tasks_composes():
    """TasksView mounts without error."""
    app = TasksTestApp()
    async with app.run_test(size=(120, 40)):
        view = app.query_one(TasksView)
        assert view is not None


@pytest.mark.asyncio
async def test_tasks_has_research_panel():
    """TasksView contains the research queue panel."""
    app = TasksTestApp()
    async with app.run_test(size=(120, 40)):
        panel = app.query_one("#research-status", Static)
        assert panel is not None


@pytest.mark.asyncio
async def test_tasks_update_state():
    """update_state populates FSM state and uptime."""
    app = TasksTestApp()
    async with app.run_test(size=(120, 40)) as pilot:
        view = app.query_one(TasksView)
        view.update_state({"fsm_state": "active", "uptime": 7200.0})
        await pilot.pause()
        text = str(app.query_one("#state-status", Static).render())
        assert "active" in text
        assert "2h" in text


# ---------------------------------------------------------------------------
# AGENTS TESTS
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_agents_composes():
    """AgentsView mounts without error."""
    app = AgentsTestApp()
    async with app.run_test(size=(120, 40)):
        view = app.query_one(AgentsView)
        assert view is not None


@pytest.mark.asyncio
async def test_agents_has_toolsets():
    """AgentsView contains the toolsets panel."""
    app = AgentsTestApp()
    async with app.run_test(size=(120, 40)):
        panel = app.query_one("#toolset-list", Static)
        assert panel is not None


@pytest.mark.asyncio
async def test_agents_has_autonomy():
    """AgentsView contains the autonomy matrix panel."""
    app = AgentsTestApp()
    async with app.run_test(size=(120, 40)):
        detail = app.query_one("#autonomy-detail", Static)
        assert detail is not None
        text = str(detail.render())
        assert "SAFE" in text
        assert "ASK_FIRST" in text


@pytest.mark.asyncio
async def test_agents_has_privacy():
    """AgentsView contains the privacy tiers panel."""
    app = AgentsTestApp()
    async with app.run_test(size=(120, 40)):
        detail = app.query_one("#privacy-detail", Static)
        assert detail is not None
        text = str(detail.render())
        assert "NEVER_LEAVE" in text
        assert "SENSITIVE" in text
