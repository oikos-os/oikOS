"""Tests for TUI widgets — header and sidebar."""
from __future__ import annotations

import pytest
from textual.app import App, ComposeResult

from core.interface.tui.widgets.header import OikOSHeader


class HeaderTestApp(App):
    def compose(self) -> ComposeResult:
        yield OikOSHeader()


@pytest.mark.asyncio
async def test_header_no_version():
    """Header no longer displays the version string."""
    app = HeaderTestApp()
    async with app.run_test(size=(120, 5)) as pilot:
        header = app.query_one(OikOSHeader)
        header.version = "2.0.0"
        await pilot.pause()
        rendered = str(header.render())
        assert "v2.0.0" not in rendered
        assert "oikOS" not in rendered


@pytest.mark.asyncio
async def test_header_renders_view_name():
    """Header shows active view name, no 'Room:' label."""
    app = HeaderTestApp()
    async with app.run_test(size=(120, 5)) as pilot:
        header = app.query_one(OikOSHeader)
        header.switch_view("vault")
        await pilot.pause()
        rendered = str(header.render())
        assert "Vault" in rendered
        assert "Room:" not in rendered


@pytest.mark.asyncio
async def test_header_renders_model():
    """Header shows model with diamond prefix and middle-dot separators."""
    app = HeaderTestApp()
    async with app.run_test(size=(120, 5)) as pilot:
        header = app.query_one(OikOSHeader)
        header.model_display = "Auto \u2192 qwen2.5:14b"
        await pilot.pause()
        rendered = str(header.render())
        assert "qwen2.5:14b" in rendered
        assert "\u25c8" in rendered
        assert "\u00b7" in rendered


from core.interface.tui.widgets.sidebar import OikOSSidebar


class SidebarTestApp(App):
    CSS = "OikOSSidebar { width: 26; }"

    def compose(self) -> ComposeResult:
        yield OikOSSidebar()


@pytest.mark.asyncio
async def test_sidebar_renders():
    app = SidebarTestApp()
    async with app.run_test(size=(80, 24)) as pilot:
        sidebar = app.query_one(OikOSSidebar)
        assert sidebar is not None


@pytest.mark.asyncio
async def test_sidebar_shows_rooms():
    app = SidebarTestApp()
    async with app.run_test(size=(80, 24)) as pilot:
        sidebar = app.query_one(OikOSSidebar)
        sidebar.update_rooms(
            [{"id": "home", "name": "Home"}, {"id": "code", "name": "Code"}],
            active_id="home",
        )
        await pilot.pause()
        room_list = sidebar.query_one("#room-list")
        assert room_list is not None


@pytest.mark.asyncio
async def test_sidebar_collapse():
    app = SidebarTestApp()
    async with app.run_test(size=(80, 24)) as pilot:
        sidebar = app.query_one(OikOSSidebar)
        sidebar.collapsed = True
        await pilot.pause()
        assert sidebar.has_class("collapsed")


@pytest.mark.asyncio
async def test_sidebar_lowercase_labels():
    """Sidebar uses lowercase labels, not ALL CAPS."""
    app = SidebarTestApp()
    async with app.run_test(size=(80, 24)) as pilot:
        sidebar = app.query_one(OikOSSidebar)
        labels = sidebar.query(".sidebar-label")
        for label in labels:
            rendered = str(label.render())
            assert rendered == rendered.lower(), f"Label should be lowercase: {rendered}"
        # Confirm no ALL CAPS headings remain
        old_headings = sidebar.query(".sidebar-heading")
        assert len(old_headings) == 0, "No sidebar-heading class should remain"
