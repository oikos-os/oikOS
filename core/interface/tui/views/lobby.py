"""Lobby view — logo, status line, doctrine quote, human-readable activity."""
from __future__ import annotations

import random

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widget import Widget
from textual.widgets import Static

from core.interface.boot import DOCTRINE_QUOTES as _RAW_QUOTES
from core.interface.tui.events import translate_events
from core.interface.tui.logo import render_logo_text

_QUOTES = [" ".join(q) for q in _RAW_QUOTES]


class LobbyView(Widget, can_focus=True):
    """Home screen — logo, status, doctrine quote, recent activity."""

    def compose(self) -> ComposeResult:
        with Vertical(id="lobby-container"):
            yield Static("", id="lobby-logo", classes="lobby-logo")
            yield Static("", id="lobby-status", classes="lobby-status")
            yield Static(
                f'"{random.choice(_QUOTES)}"',
                id="lobby-quote",
                classes="lobby-quote",
            )
            yield Static("", id="lobby-activity", classes="lobby-activity")

    def on_mount(self) -> None:
        self.query_one("#lobby-logo", Static).update(render_logo_text())

    def update_system(self, state: dict, room: dict, vault: dict) -> None:
        version = state.get("version", "?.?.?")
        model = state.get("model", "---")
        files = vault.get("unique_files", "--")
        tools = state.get("tools", "--")
        providers = state.get("providers", "--")
        parts = [
            f"⌂ v{version}",
            f"{files} files",
            f"{tools} tools",
            f"{providers} providers",
            f"◈ Auto → {model}",
        ]
        self.query_one("#lobby-status", Static).update(" · ".join(parts))

    def update_activity(self, events: list[dict]) -> None:
        entries = translate_events(events)
        if not entries:
            self.query_one("#lobby-activity", Static).update("")
            return
        lines = [f"{e['time']}   {e['text']}" for e in entries]
        self.query_one("#lobby-activity", Static).update("\n".join(lines))
