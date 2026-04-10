"""Agents view — toolsets, autonomy matrix, privacy tiers."""
from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widget import Widget
from textual.widgets import Static


# Autonomy and privacy tier data (matches framework/middleware config)
_AUTONOMY_TIERS = {
    "SAFE": ["vault.search", "vault.stats", "system.status", "system.state", "git.log", "git.status"],
    "ASK_FIRST": ["browser.*", "file.write", "file.delete", "google.gmail_create_draft", "google.gcal_create_event"],
    "PROHIBITED": [],
}

_PRIVACY_TIERS = {
    "NEVER_LEAVE": ["vault content", "identity assertions", "local inference"],
    "SENSITIVE": ["file contents", "browser data", "config values"],
    "SAFE": ["system status", "FSM state", "tool metadata"],
}


class AgentsView(Widget, can_focus=True):
    """Agents screen: tool inventory, autonomy matrix, privacy tiers."""

    def compose(self) -> ComposeResult:
        yield Static("\u25c8 Agent Capabilities", id="agents-header")

        with Vertical(id="agents-scroll"):
            with Vertical(id="agents-toolsets"):
                yield Static("toolsets", classes="section-label")
                yield Static("\u2500" * 35, classes="section-separator")
                yield Static("(loading...)", id="toolset-list")

            with Vertical(id="agents-autonomy"):
                yield Static("autonomy", classes="section-label")
                yield Static("\u2500" * 35, classes="section-separator")
                yield Static(self._format_autonomy(), id="autonomy-detail")

            with Vertical(id="agents-privacy"):
                yield Static("privacy", classes="section-label")
                yield Static("\u2500" * 35, classes="section-separator")
                yield Static(self._format_privacy(), id="privacy-detail")

    def update_tools(self, tools_info: dict) -> None:
        """Update toolsets from API data."""
        toolsets = tools_info.get("toolsets", {})
        total = tools_info.get("total", 0)
        set_count = len(toolsets)

        if total:
            self.query_one("#agents-header", Static).update(
                f"\u25c8 Agent Capabilities \u2014 {total} tools across {set_count} sets"
            )
        self.query_one("#toolset-list", Static).update(self._format_toolsets(toolsets))

    def _format_toolsets(self, toolsets: dict[str, list[str]]) -> str:
        """Format toolset names with counts and tool names inline."""
        if not toolsets:
            return "(registry not available)"
        lines = []
        for name, tools in sorted(toolsets.items()):
            tool_names = ", ".join(tools[:6])
            if len(tools) > 6:
                tool_names += ", ..."
            lines.append(f"{name} ({len(tools)})  {tool_names}")
        return "\n".join(lines)

    def _format_autonomy(self) -> str:
        """Format autonomy tiers for display."""
        lines = []
        for level, tools in _AUTONOMY_TIERS.items():
            items = ", ".join(tools) if tools else "(none configured)"
            lines.append(f"{level}  {items}")
        return "\n".join(lines)

    def _format_privacy(self) -> str:
        """Format privacy tiers for display."""
        lines = []
        for tier, items in _PRIVACY_TIERS.items():
            lines.append(f"{tier}  {', '.join(items)}")
        return "\n".join(lines)
