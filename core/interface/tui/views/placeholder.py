"""Generic placeholder view for screens not yet implemented."""
from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Center, Middle
from textual.widget import Widget
from textual.widgets import Static


class PlaceholderView(Widget):
    """Placeholder content for views coming in later TUI phases."""

    def __init__(self, title: str, phase: str = "TUI-2", **kwargs) -> None:
        super().__init__(**kwargs)
        self._title = title
        self._phase = phase

    def compose(self) -> ComposeResult:
        with Center():
            with Middle():
                yield Static(f"\u25c8 {self._title}", classes="placeholder-title")
                yield Static(f"Coming in {self._phase}", classes="placeholder-subtitle")
                yield Static("")
                yield Static("Use F1-F7 to navigate", classes="dim")
