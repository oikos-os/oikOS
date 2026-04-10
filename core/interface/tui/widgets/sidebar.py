"""Collapsible sidebar — rooms, providers, tools, Google status."""
from __future__ import annotations

from textual.app import ComposeResult
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Static


class OikOSSidebar(Widget):
    """Left sidebar showing rooms, provider status, and tool info."""

    collapsed = reactive(False)

    def compose(self) -> ComposeResult:
        yield Static("\u2302 oikOS", id="sidebar-title", classes="sidebar-item-active")
        yield Static("rooms", classes="sidebar-label")
        yield Static("  (loading...)", id="room-list", classes="sidebar-item")
        yield Static("providers", classes="sidebar-label")
        yield Static("  (loading...)", id="provider-status", classes="sidebar-item")
        yield Static("tools", classes="sidebar-label")
        yield Static("  -- loaded", id="tool-count", classes="sidebar-item")
        yield Static("google", classes="sidebar-label")
        yield Static("  (loading...)", id="google-status", classes="sidebar-item")

    def watch_collapsed(self, value: bool) -> None:
        if value:
            self.add_class("collapsed")
        else:
            self.remove_class("collapsed")

    def update_rooms(self, rooms: list[dict], active_id: str = "") -> None:
        """Update the room list display."""
        lines = []
        for r in rooms:
            marker = "\u25b8 " if r["id"] == active_id else "  "
            lines.append(f"{marker}{r.get('name', r['id'])}")
        text = "\n".join(lines) if lines else "  (none)"
        self.query_one("#room-list", Static).update(text)

    def update_providers(self, models: dict) -> None:
        """Update provider status from /api/models response.

        API returns {"local": [...], "cloud": [{"provider": "gemini", ...}, ...]}.
        Extract distinct provider names from model entries.
        """
        providers: dict[str, bool] = {}
        for category, model_list in models.items():
            if not isinstance(model_list, list):
                continue
            if category == "local" and model_list:
                providers["local"] = True
            for m in model_list:
                if isinstance(m, dict) and m.get("provider"):
                    providers[m["provider"]] = True
        lines = [f"  {name} \u25cf" for name in providers] if providers else ["  (none)"]
        self.query_one("#provider-status", Static).update("\n".join(lines))

    def update_tools(self, count: int) -> None:
        self.query_one("#tool-count", Static).update(f"  {count} loaded")

    def update_google(self, google_status: dict) -> None:
        """Update Google services status."""
        from core.interface.tui.client import scopes_to_services

        if google_status.get("connected"):
            services = scopes_to_services(google_status.get("scopes", []))
            text = "\n".join(f"  {s} \u25cf" for s in services) if services else "  Connected \u25cf"
        else:
            text = "  Not connected \u25cb"
        self.query_one("#google-status", Static).update(text)
