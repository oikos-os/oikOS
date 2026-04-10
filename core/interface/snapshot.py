"""oikOS bare-command snapshot — disk + API state at a glance."""

from __future__ import annotations

import logging

from rich import box
from rich.console import Console, Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

import httpx

from core.interface.config import PROJECT_ROOT

log = logging.getLogger(__name__)

API_TIMEOUT = 0.5
VAULT_DIR = PROJECT_ROOT / "vault"


def _collect_disk_state() -> dict:
    """Collect version, active room, provider, vault count, theme from disk."""
    state: dict = {}

    try:
        from core import __version__
        state["version"] = __version__
    except Exception:
        state["version"] = "?"

    try:
        from core.rooms.manager import get_room_manager
        room = get_room_manager().get_active_room()
        state["room"] = room.name
    except Exception:
        state["room"] = "home"

    try:
        import tomllib
        toml_path = PROJECT_ROOT / "providers.toml"
        if toml_path.exists():
            with open(toml_path, "rb") as f:
                data = tomllib.load(f)
            state["provider"] = data.get("general", {}).get("default", "local")
        else:
            state["provider"] = "local"
    except Exception:
        state["provider"] = "local"

    try:
        count = sum(
            1 for f in VAULT_DIR.rglob("*.md")
            if not any(p.name.startswith(".") for p in f.relative_to(VAULT_DIR).parents)
        ) if VAULT_DIR.is_dir() else 0
        state["vault_entries"] = count
    except Exception:
        state["vault_entries"] = 0

    try:
        from core.interface.settings import get_setting
        state["theme"] = get_setting("theme") or "amber"
    except Exception:
        state["theme"] = "amber"

    return state


def _collect_api_state() -> dict | None:
    """Single GET to the local API for live state. Returns None on any failure."""
    try:
        from core.interface.settings import get_setting
        url = f"http://localhost:{get_setting('api_port')}/api/system/state"
        resp = httpx.get(url, timeout=API_TIMEOUT)
        resp.raise_for_status()
        return resp.json()
    except Exception:
        return None


def _format_uptime(seconds: float) -> str:
    """Convert seconds to human-readable uptime string."""
    if seconds < 60:
        return f"{int(seconds)}s"
    if seconds < 3600:
        return f"{int(seconds // 60)}m"
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    if minutes:
        return f"{hours}h {minutes}m"
    return f"{hours}h"


def render_snapshot(console: Console) -> None:
    """Merge disk + API state and render a Rich Panel snapshot."""
    disk = _collect_disk_state()
    api = _collect_api_state()

    version = disk.get("version", "?")
    header = Text()
    header.append(f"  \u2302 oikOS v{version}", style="oikos.bright")
    header.append(" \u2014 The home for AI agents", style="oikos.dim")

    table = Table(show_header=False, box=None, padding=(0, 2), expand=True)
    table.add_column("key", style="oikos.primary", no_wrap=True)
    table.add_column("value", style="oikos.dim")

    table.add_row("room", disk.get("room", "home"))
    table.add_row("provider", disk.get("provider", "local"))
    table.add_row("vault", f"{disk.get('vault_entries', 0)} entries")
    table.add_row("theme", disk.get("theme", "amber"))

    if api:
        fsm = api.get("fsm_state", "unknown").lower()
        table.add_row("state", fsm)
        uptime = api.get("uptime")
        if uptime is not None:
            table.add_row("uptime", _format_uptime(float(uptime)))
    else:
        table.add_row("server", "offline")

    hint = Text()
    if api:
        hint.append("  oikos tui", style="oikos.primary")
        hint.append("  open TUI   ", style="oikos.dim")
        hint.append("oikos query", style="oikos.primary")
        hint.append("  ask a question   ", style="oikos.dim")
    else:
        hint.append("  oikos serve", style="oikos.primary")
        hint.append("  start server   ", style="oikos.dim")
        hint.append("oikos tui", style="oikos.primary")
        hint.append("  open TUI   ", style="oikos.dim")
    hint.append("oikos help", style="oikos.primary")
    hint.append("  all commands", style="oikos.dim")

    panel = Panel(
        Group(header, "", table, "", hint),
        box=box.ROUNDED,
        border_style="oikos.border",
        padding=(1, 2),
    )
    console.print(panel)
