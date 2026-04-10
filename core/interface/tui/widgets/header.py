"""Custom header bar — shows active view, model, vault stats, uptime."""
from __future__ import annotations

from textual.reactive import reactive
from textual.widgets import Static


def _format_uptime(seconds: float) -> str:
    """Format seconds into human-readable uptime string."""
    s = int(seconds)
    if s < 60:
        return f"{s}s"
    if s < 3600:
        return f"{s // 60}m"
    h, m = divmod(s, 3600)
    return f"{h}h {m // 60:02d}m"


_VIEW_LABELS: dict[str, str] = {
    "lobby": "Home",
    "chat": "Chat",
    "vault": "Vault",
    "rooms": "Rooms",
    "settings": "Settings",
    "tasks": "Tasks",
    "agents": "Agents",
}


class OikOSHeader(Static):
    """Persistent header bar showing system status."""

    view_name = reactive("Home")
    model_display = reactive("---")
    vault_info = reactive("-- files")
    uptime_seconds = reactive(0.0)

    def render(self) -> str:
        up = _format_uptime(self.uptime_seconds)
        return f"\u25c7 {self.view_name} \u00b7 \u25c8 {self.model_display} \u00b7 {self.vault_info} \u00b7 \u2191{up}"

    def switch_view(self, view_id: str) -> None:
        self.view_name = _VIEW_LABELS.get(view_id, view_id.title())

    def update_from_api(self, state: dict, room: dict, vault: dict, models: dict) -> None:
        """Bulk update from API response dicts."""
        if vault.get("unique_files") is not None:
            self.vault_info = f"{vault['unique_files']} files"
        if state.get("uptime") is not None:
            self.uptime_seconds = state["uptime"]
        # Model display: check room config first
        room_model = room.get("model", {})
        if isinstance(room_model, dict) and room_model.get("model"):
            self.model_display = room_model["model"]
        else:
            self.model_display = f"Auto \u2192 {state.get('model', '---')}"
