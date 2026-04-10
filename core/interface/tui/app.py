"""OikOSApp — the main Textual TUI application for oikOS."""
from __future__ import annotations

import asyncio
import logging
import random
import subprocess
import sys
import time

from rich.console import Console
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.widgets import ContentSwitcher, Footer

from core.interface.boot import DOCTRINE_QUOTES
from core.interface.tui.client import OikOSClient
from core.interface.tui.logo import render_logo_text
from core.interface.tui.views.agents import AgentsView
from core.interface.tui.views.chat import ChatView
from core.interface.tui.views.lobby import LobbyView
from core.interface.tui.views.rooms import RoomsView
from core.interface.tui.views.settings import SettingsView
from core.interface.tui.views.tasks import TasksView
from core.interface.tui.views.vault import VaultView
from core.interface.tui.widgets.approval_bar import ApprovalBar
from core.interface.tui.widgets.notification_bar import NotificationBar
from core.interface.tui.widgets.header import OikOSHeader
from core.interface.tui.widgets.sidebar import OikOSSidebar

log = logging.getLogger(__name__)


class OikOSFooter(Footer):
    """Footer with fixed core key ordering and view-specific keys on the right."""

    # Core actions in display order (left side, always stable)
    _CORE_ORDER = [
        "toggle_sidebar",
        "switch_view('lobby')", "switch_view('chat')", "switch_view('vault')",
        "switch_view('rooms')", "switch_view('settings')", "switch_view('tasks')",
        "switch_view('agents')",
        "reload", "quit_app",
    ]
    _CORE_SET = frozenset(_CORE_ORDER)

    def compose(self) -> ComposeResult:
        from textual.widgets._footer import FooterKey
        if not self._bindings_ready:
            return
        active = self.screen.active_bindings
        lookup: dict[str, tuple] = {}
        view_keys: list[tuple] = []
        for _, binding, enabled, tooltip in active.values():
            if not binding.show:
                continue
            if binding.action in self._CORE_SET:
                lookup[binding.action] = (binding, enabled, tooltip)
            else:
                view_keys.append((binding, enabled, tooltip))

        # Core keys — fixed order, left side
        for action in self._CORE_ORDER:
            if action not in lookup:
                continue
            binding, enabled, tooltip = lookup[action]
            yield FooterKey(
                binding.key, self.app.get_key_display(binding),
                binding.description, binding.action,
                disabled=not enabled, tooltip=tooltip,
            ).data_bind(compact=Footer.compact)

        # View-specific keys — right side, docked
        for binding, enabled, tooltip in view_keys:
            yield FooterKey(
                binding.key, self.app.get_key_display(binding),
                binding.description, binding.action,
                disabled=not enabled, tooltip=tooltip,
                classes="-view-action",
            ).data_bind(compact=Footer.compact)

        # Command palette — far right (accessed directly; may have show=False)
        if self.show_command_palette and self.app.ENABLE_COMMAND_PALETTE:
            try:
                _, binding, enabled, tooltip = active[self.app.COMMAND_PALETTE_BINDING]
            except KeyError:
                pass
            else:
                yield FooterKey(
                    binding.key, self.app.get_key_display(binding),
                    binding.description, binding.action,
                    classes="-command-palette",
                    disabled=not enabled, tooltip=binding.tooltip or binding.description,
                )

    def bindings_changed(self, screen) -> None:
        super().bindings_changed(screen)
        self.call_after_refresh(self._reapply_highlight)

    def _reapply_highlight(self) -> None:
        if hasattr(self.app, "_current_view"):
            self.app._highlight_footer(self.app._current_view)


def run_tui_boot_splash() -> None:
    """Show logo splash for 2 seconds before TUI starts."""
    console = Console()
    console.clear()
    logo = render_logo_text()
    console.print(logo)
    console.print("[#8B6914]The home for AI agents[/]")
    console.print()
    quote = " ".join(random.choice(DOCTRINE_QUOTES))
    console.print(f'[#D4A017]"{quote}"[/]')
    time.sleep(2)
    console.clear()


class OikOSApp(App):
    """oikOS — The home for AI agents."""

    CSS_PATH = "styles.tcss"
    TITLE = "oikOS"
    SUB_TITLE = "The home for AI agents"

    BINDINGS = [
        Binding("f1", "switch_view('lobby')", "Home"),
        Binding("f2", "switch_view('chat')", "Chat"),
        Binding("f3", "switch_view('vault')", "Vault"),
        Binding("f4", "switch_view('rooms')", "Rooms"),
        Binding("f5", "switch_view('settings')", "Settings"),
        Binding("f6", "switch_view('tasks')", "Tasks"),
        Binding("f7", "switch_view('agents')", "Agents"),
        Binding("f9", "show_approvals", "Approvals", show=False),
        Binding("ctrl+b", "toggle_sidebar", "Sidebar"),
        Binding("ctrl+r", "reload", "Reload"),
        Binding("ctrl+q", "quit_app", "Quit"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.api_client = OikOSClient()
        self._server_proc: subprocess.Popen | None = None
        self._current_view: str = "lobby"

    def get_key_display(self, binding: Binding) -> str:
        display = super().get_key_display(binding)
        if display.startswith("^"):
            return "Ctrl+" + display[1:].upper()
        return display.upper()

    def compose(self) -> ComposeResult:
        yield OikOSHeader()
        with Horizontal(id="content-area"):
            yield OikOSSidebar()
            with ContentSwitcher(initial="lobby", id="content-switcher"):
                yield LobbyView(id="lobby")
                yield ChatView(id="chat")
                yield VaultView(id="vault")
                yield RoomsView(id="rooms")
                yield SettingsView(id="settings")
                yield TasksView(id="tasks")
                yield AgentsView(id="agents")
        yield ApprovalBar()
        yield NotificationBar()
        yield OikOSFooter()

    async def on_mount(self) -> None:
        """Initialize: connect to API server, load data, apply theme."""
        # Apply theme
        try:
            from core.interface.theme import get_effective_theme_name
            theme = get_effective_theme_name()
        except Exception:
            theme = "amber"
        if theme and theme != "amber":
            self.screen.add_class(f"theme-{theme}")

        # Ensure API server is running
        if not await self.api_client.is_reachable():
            await self._start_server()

        # Load initial data
        self.set_interval(1, self._tick_uptime)
        self.set_interval(3, self._poll_approvals)
        self.set_interval(3.0, self._poll_notifications)
        self.run_worker(self._load_initial_data)
        self.call_after_refresh(self._highlight_footer, "lobby")

    async def _start_server(self) -> None:
        """Start the API server as a background subprocess."""
        self._server_proc = subprocess.Popen(
            [sys.executable, "-m", "uvicorn",
             "core.interface.api.server:app_prod",
             "--host", "127.0.0.1", "--port", str(self.api_client.port),
             "--log-level", "warning"],
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        # Wait for server to be ready
        for _ in range(20):
            await asyncio.sleep(0.5)
            if await self.api_client.is_reachable():
                return
        self.notify("API server failed to start", severity="error")

    async def _load_initial_data(self) -> None:
        """Fetch state from API and populate widgets."""
        state = await self.api_client.state()
        room = await self.api_client.active_room()
        vault = await self.api_client.vault_stats()
        models = await self.api_client.models()
        rooms = await self.api_client.rooms()
        google = await self.api_client.google_status()
        events = await self.api_client.events()

        # Update header
        header = self.query_one(OikOSHeader)
        header.update_from_api(state, room, vault, models)

        # Update sidebar
        sidebar = self.query_one(OikOSSidebar)
        sidebar.update_rooms(rooms, active_id=room.get("id", ""))
        sidebar.update_providers(models)
        tools_info = await self.api_client.tools()
        sidebar.update_tools(tools_info.get("total", 0))
        sidebar.update_google(google)

        # Update chat view
        chat = self.query_one("#chat", ChatView)
        chat.update_models(models)
        chat.update_room(room.get("name", "Home"))

        # Enrich state with tools/providers counts for lobby status line
        state["tools"] = tools_info.get("total", 0)
        provider_names = set()
        for cat, mlist in models.items():
            if not isinstance(mlist, list):
                continue
            if cat == "local" and mlist:
                provider_names.add("local")
            for m in mlist:
                if isinstance(m, dict) and m.get("provider"):
                    provider_names.add(m["provider"])
        state["providers"] = len(provider_names)

        # Update lobby
        lobby = self.query_one("#lobby", LobbyView)
        lobby.update_system(state, room, vault)
        lobby.update_activity(events)

        # Update vault view header
        vault_view = self.query_one("#vault", VaultView)
        vault_view.update_header(vault.get("unique_files", 0))

        # Update rooms view
        rooms_view = self.query_one("#rooms", RoomsView)
        rooms_view.update_rooms(rooms, active_id=room.get("id", ""))

        # Update settings view
        claude = await self.api_client.claude_status()
        settings_view = self.query_one("#settings", SettingsView)
        settings_view.update_providers(models)
        settings_view.update_claude(claude)
        settings_view.update_google(google)

        # Update agents view
        agents_view = self.query_one("#agents", AgentsView)
        agents_view.update_tools(tools_info)

        # Update tasks view
        tasks_view = self.query_one("#tasks", TasksView)
        tasks_view.update_state(state)
        tasks_view.update_jobs(events)

    def _tick_uptime(self) -> None:
        """Increment uptime display every second."""
        try:
            header = self.query_one(OikOSHeader)
            header.uptime_seconds += 1
        except Exception as e:
            log.debug("uptime tick suppressed: %s", e)

    async def action_show_approvals(self) -> None:
        """Open the approval review modal (F9)."""
        pending = await self.api_client.pending_approvals()
        from core.interface.tui.views.approvals import ApprovalModal
        await self.push_screen(ApprovalModal(pending))

    async def _poll_approvals(self) -> None:
        """Poll for pending approval requests every 3 seconds."""
        try:
            pending = await self.api_client.pending_approvals()
            self.query_one(ApprovalBar).update_pending(pending)
        except Exception as e:
            log.debug("approval poll suppressed: %s", e)

    async def _poll_notifications(self) -> None:
        """Poll for pending notifications every 3 seconds (T-119).

        Fetches the full ring buffer on every tick (no `since` filter) so the
        widget stays visible as long as items exist — matches the T-102
        ApprovalBar precedent. The ring buffer is bounded (deque maxlen=50)
        so the response size is always capped.
        """
        try:
            pending = await self.api_client.pending_notifications()
            self.query_one(NotificationBar).update_pending(pending)
        except Exception as e:
            log.debug("notification poll suppressed: %s", e)

    def action_switch_view(self, view_name: str) -> None:
        """Switch the main content area to a different view."""
        self._current_view = view_name
        self.query_one("#content-switcher", ContentSwitcher).current = view_name
        self.query_one(OikOSHeader).switch_view(view_name)
        # Defer focus until after the ContentSwitcher has made the view visible
        self.call_after_refresh(self._activate_view, view_name)

    def _activate_view(self, view_name: str) -> None:
        """Focus the view and highlight its footer key (runs after refresh)."""
        self.set_focus(self.query_one(f"#{view_name}"))
        self._highlight_footer(view_name)

    def _highlight_footer(self, view_name: str) -> None:
        """Mark the active view's footer key as highlighted."""
        from textual.widgets._footer import FooterKey

        target_action = f"switch_view('{view_name}')"
        for fk in self.query(FooterKey):
            if fk.action == target_action:
                fk.add_class("-active-view")
            else:
                fk.remove_class("-active-view")

    def action_toggle_sidebar(self) -> None:
        """Toggle sidebar visibility."""
        sidebar = self.query_one(OikOSSidebar)
        sidebar.collapsed = not sidebar.collapsed

    async def action_reload(self) -> None:
        """Reload all data from the API server."""
        self.notify("Reloading...")
        await self._load_initial_data()
        self._activate_view(self._current_view)
        self.notify("Reloaded", severity="information")

    async def action_quit_app(self) -> None:
        """Clean shutdown — terminate server if we started it."""
        if self._server_proc and self._server_proc.poll() is None:
            self._server_proc.terminate()
            self._server_proc = None
        await self.api_client.close()
        self.exit()

    async def on_rooms_view_room_switched(self, event: RoomsView.RoomSwitched) -> None:
        """Refresh header, sidebar, and chat after room switch."""
        room = await self.api_client.active_room()
        state = await self.api_client.state()
        vault = await self.api_client.vault_stats()
        models = await self.api_client.models()
        rooms = await self.api_client.rooms()

        self.query_one(OikOSHeader).update_from_api(state, room, vault, models)
        self.query_one(OikOSSidebar).update_rooms(rooms, active_id=room.get("id", ""))
        self.query_one("#chat", ChatView).update_room(room.get("name", "Home"))
        self.query_one("#chat", ChatView).update_models(models)

