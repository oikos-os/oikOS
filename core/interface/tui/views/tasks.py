"""Tasks view — research queue and running jobs (informational)."""
from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widget import Widget
from textual.widgets import Static


class TasksView(Widget, can_focus=True):
    """Tasks screen: research queue status and running daemon jobs."""

    def compose(self) -> ComposeResult:
        yield Static(
            "\u25c8 Tasks & Research",
            id="tasks-header",
        )
        with Vertical(id="tasks-scroll"):
            with Vertical(id="tasks-research"):
                yield Static("research", classes="section-label")
                yield Static("\u2500" * 35, classes="section-separator")
                yield Static(
                    "Nothing scheduled.",
                    id="research-status",
                    classes="tasks-empty",
                )

            with Vertical(id="tasks-jobs"):
                yield Static("jobs", classes="section-label")
                yield Static("\u2500" * 35, classes="section-separator")
                yield Static(
                    "(loading...)",
                    id="jobs-status",
                )

            with Vertical(id="tasks-state"):
                yield Static("system", classes="section-label")
                yield Static("\u2500" * 35, classes="section-separator")
                yield Static(
                    "(loading...)",
                    id="state-status",
                )

    def update_state(self, state: dict) -> None:
        """Update system state display from /api/state."""
        fsm = state.get("fsm_state", "unknown")
        uptime = state.get("uptime", 0)
        hours = int(uptime) // 3600
        minutes = (int(uptime) % 3600) // 60
        lines = [
            f"state         {fsm}",
            f"uptime        {hours}h {minutes}m",
        ]
        self.query_one("#state-status", Static).update("\n".join(lines))

    def update_jobs(self, events: list[dict]) -> None:
        """Update running jobs from recent events (human-readable)."""
        from core.interface.tui.events import translate_events

        entries = translate_events(events)
        if not entries:
            self.query_one("#jobs-status", Static).update("No recent activity")
            return
        lines = [f"{e['time']}  {e['text']}" for e in entries]
        self.query_one("#jobs-status", Static).update("\n".join(lines))
