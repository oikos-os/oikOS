"""Rooms view — browse and switch rooms, inspect room config."""
from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.widget import Widget
from textual.widgets import ListItem, ListView, Static


class RoomsView(Widget, can_focus=True):

    class RoomSwitched(Message):
        """Posted when the active room changes."""
        def __init__(self, room_id: str, room_name: str) -> None:
            super().__init__()
            self.room_id = room_id
            self.room_name = room_name
    """Rooms screen: list all rooms, show config, switch active room."""

    BINDINGS = [
        Binding("s", "switch_room", "Switch", show=True),
    ]

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._rooms: list[dict] = []
        self._active_id: str = ""
        self._selected_index: int = 0

    def compose(self) -> ComposeResult:
        yield Static(
            "\u25c8 Rooms \u2014 loading...",
            id="rooms-header",
        )
        with Horizontal(id="rooms-content"):
            with Vertical(id="rooms-list-panel"):
                yield ListView(id="rooms-list")
            with Vertical(id="rooms-config-panel"):
                yield Static("Select a room to view details", id="room-config-detail")

    def update_rooms(self, rooms: list[dict], active_id: str = "") -> None:
        """Populate the room list and config panel from API data."""
        self._rooms = rooms
        self._active_id = active_id
        self._rebuild_list()
        self._update_header()
        if rooms:
            self._show_config(0)

    def _rebuild_list(self) -> None:
        """Rebuild the ListView items from cached room data."""
        lv = self.query_one("#rooms-list", ListView)
        lv.clear()
        for room in self._rooms:
            marker = "\u25b8 " if room.get("id") == self._active_id else "  "
            label = f"{marker}{room.get('name', room.get('id', '?'))}"
            lv.append(ListItem(Static(label)))

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        """When a room is selected in the list, show its config."""
        if event.list_view.id != "rooms-list":
            return
        self._selected_index = event.list_view.index or 0
        self._show_config(self._selected_index)

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        """Update config panel as user navigates the list."""
        if event.list_view.id != "rooms-list":
            return
        idx = event.list_view.index
        if idx is not None and 0 <= idx < len(self._rooms):
            self._selected_index = idx
            self._show_config(idx)

    def _show_config(self, index: int) -> None:
        """Display room configuration for the given index."""
        if index < 0 or index >= len(self._rooms):
            return
        room = self._rooms[index]
        detail = self.query_one("#room-config-detail", Static)

        # Extract fields
        name = room.get("name", room.get("id", "?"))
        rid = room.get("id", "?")
        desc = room.get("description") or "(no description)"

        # Model config
        model_cfg = room.get("model", {})
        if isinstance(model_cfg, dict):
            provider = model_cfg.get("provider") or "Auto"
            model = model_cfg.get("model") or "Auto"
            model_str = f"{provider}/{model}" if provider != "Auto" else "Auto"
        else:
            model_str = "Auto"

        # Providers
        allowed = room.get("allowed_providers")
        providers_str = ", ".join(allowed) if allowed else "all"

        # Toolsets
        toolsets = room.get("toolsets")
        toolsets_str = ", ".join(toolsets) if toolsets else "all"

        # Vault scope
        vs = room.get("vault_scope", {})
        if isinstance(vs, dict):
            mode = vs.get("mode", "all")
            tags = vs.get("tags", [])
            vault_str = f"{mode}" + (f" [{', '.join(tags)}]" if tags else "")
        else:
            vault_str = "all"

        # Autonomy
        auto = room.get("autonomy", {})
        if isinstance(auto, dict):
            overrides = auto.get("overrides", {})
            auto_str = ", ".join(f"{k}={v}" for k, v in overrides.items()) if overrides else "default"
        else:
            auto_str = "default"

        active_marker = "  \u25b8 active" if rid == self._active_id else ""

        lines = [
            f"[bold]{name}[/]{active_marker}",
            f"{desc}",
            "",
            f"model         {model_str}",
            f"providers     {providers_str}",
            f"toolsets      {toolsets_str}",
            f"vault tags    {vault_str}",
            f"autonomy      {auto_str}",
        ]
        detail.update("\n".join(lines))

    def _update_header(self) -> None:
        """Update the header with room count."""
        count = len(self._rooms)
        self.query_one("#rooms-header", Static).update(
            f"\u25c8 Rooms \u2014 {count} configured"
        )

    async def action_switch_room(self) -> None:
        """Switch to the currently selected room."""
        if not self._rooms or self._selected_index >= len(self._rooms):
            self.notify("No room selected", severity="warning")
            return
        room = self._rooms[self._selected_index]
        rid = room.get("id", "")
        if rid == self._active_id:
            self.notify(f"Already in {room.get('name', rid)}")
            return
        try:
            result = await self.app.api_client.switch_room(rid)
            if result:
                self._active_id = rid
                self._rebuild_list()
                self._show_config(self._selected_index)
                self.post_message(self.RoomSwitched(rid, room.get("name", rid)))
                self.notify(f"Switched to {room.get('name', rid)}")
            else:
                self.notify("Switch failed", severity="error")
        except Exception:
            self.notify("Switch failed", severity="error")
