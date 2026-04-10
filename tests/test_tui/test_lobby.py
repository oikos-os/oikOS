"""Tests for the Lobby view."""
from __future__ import annotations

import pytest
from textual.app import App, ComposeResult

from core.interface.tui.views.lobby import LobbyView


class LobbyTestApp(App):
    def compose(self) -> ComposeResult:
        yield LobbyView(id="lobby")


@pytest.mark.asyncio
async def test_lobby_has_logo():
    app = LobbyTestApp()
    async with app.run_test(size=(120, 40)) as pilot:
        logo = app.query_one("#lobby-logo")
        assert logo is not None


@pytest.mark.asyncio
async def test_lobby_has_status_line():
    app = LobbyTestApp()
    async with app.run_test(size=(120, 40)) as pilot:
        status = app.query_one("#lobby-status")
        assert status is not None


@pytest.mark.asyncio
async def test_lobby_has_doctrine_quote():
    app = LobbyTestApp()
    async with app.run_test(size=(120, 40)) as pilot:
        quote = app.query_one("#lobby-quote")
        assert quote is not None
        text = str(quote.render())
        quotes = [
            "Intelligence is cheap",
            "The cloud is a loan",
            "Fix the soul",
            "Even agents",
        ]
        assert any(q in text for q in quotes)


@pytest.mark.asyncio
async def test_lobby_has_activity():
    app = LobbyTestApp()
    async with app.run_test(size=(120, 40)) as pilot:
        activity = app.query_one("#lobby-activity")
        assert activity is not None


@pytest.mark.asyncio
async def test_lobby_updates_status():
    app = LobbyTestApp()
    async with app.run_test(size=(120, 40)) as pilot:
        lobby = app.query_one(LobbyView)
        lobby.update_system(
            {"version": "2.0.0", "model": "qwen2.5:14b"},
            {"name": "Home"},
            {"unique_files": 132},
        )
        await pilot.pause()
        text = str(app.query_one("#lobby-status").render())
        assert "132" in text


@pytest.mark.asyncio
async def test_lobby_activity_human_readable():
    app = LobbyTestApp()
    async with app.run_test(size=(120, 40)) as pilot:
        lobby = app.query_one(LobbyView)
        lobby.update_activity([
            {"timestamp": "2026-03-25T15:33:00", "category": "inference",
             "type": "complete", "data": {"room": "Home"}},
        ])
        await pilot.pause()
        text = str(app.query_one("#lobby-activity").render())
        assert "Chatted in Home" in text
