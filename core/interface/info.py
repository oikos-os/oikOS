"""oikOS info — neofetch-style system overview."""

from __future__ import annotations

import logging

from rich import box
from rich.columns import Columns
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

log = logging.getLogger(__name__)

_LOGO = r"""
 ╔═══════════════╗
 ║   ██████      ║
 ║  ██    ██     ║
 ║  ██    ██     ║
 ║  ██    ██     ║
 ║   ██████      ║
 ║                ║
 ║   ◈  oikOS    ║
 ╚═══════════════╝
""".strip()


def render_info(console: Console) -> None:
    """Render neofetch-style system info with ASCII logo and live stats."""
    from core import __version__

    # Vault stats
    try:
        from core.memory.indexer import get_table_stats

        stats = get_table_stats()
        vault_str = f"{stats['unique_files']} files, {stats['total_rows']} chunks"
    except Exception:
        vault_str = "unavailable"

    # Active room + room list
    mgr = None
    active_room = None
    try:
        from core.rooms.manager import get_room_manager

        mgr = get_room_manager()
        active_room = mgr.get_active_room()
    except Exception as e:
        log.debug("room manager load suppressed: %s", e)

    # Inference model
    try:
        from core.cognition.inference import check_inference_model
        from core.interface.config import INFERENCE_MODEL

        model = INFERENCE_MODEL if check_inference_model() else "offline"
    except Exception:
        model = "unknown"

    # Backend (with URL detail)
    try:
        from core.cognition.pipeline.dispatch import get_provider_registry

        reg = get_provider_registry()
        backend_name = reg.get_default_name()
        provider = reg.get(backend_name)
        provider_label = getattr(provider, "provider_name", backend_name)
        base_url = getattr(provider, "base_url", None)
        backend = f"{provider_label} ({base_url})" if base_url else provider_label
    except Exception:
        backend = "unknown"

    # Uptime
    try:
        from core.interface.config import DAEMON_PID_FILE

        uptime_str = "running" if DAEMON_PID_FILE.exists() else "N/A"
    except Exception:
        uptime_str = "N/A"

    # Room list (reuses mgr + active_room from above)
    try:
        active_id = active_room.id if active_room else "home"
        all_rooms = mgr.list_rooms() if mgr else []
        room_parts = []
        for r in all_rooms:
            if r.id == active_id:
                room_parts.append(f"{r.name} (active)")
            else:
                room_parts.append(r.name)
        rooms_str = " \u00b7 ".join(room_parts) if room_parts else "home (active)"
    except Exception:
        rooms_str = "home (active)"

    # Tool count from live registry
    try:
        import core.framework.tools  # noqa: F401 — triggers @oikos_tool registration
        from core.framework.decorator import get_registered_tools

        _reg = get_registered_tools()
        _toolsets = {m.toolset for _, m in _reg.values() if m.toolset}
        tools_str = f"{len(_reg)} across {len(_toolsets)} toolsets"
    except Exception:
        tools_str = "unavailable"

    from core import TEST_COUNT

    separator = "[oikos.dim]────────────────────────[/]"
    lines = [
        separator,
        f"[oikos.header]OS[/]         oikOS v{__version__}",
        f"[oikos.header]Model[/]      {model}",
        f"[oikos.header]Backend[/]    {backend}",
        f"[oikos.header]Vault[/]      {vault_str}",
        f"[oikos.header]Tools[/]      {tools_str}",
        f"[oikos.header]Tests[/]      {TEST_COUNT}",
        f"[oikos.header]Uptime[/]     {uptime_str}",
        f"[oikos.header]Privacy[/]    NEVER_LEAVE enforced",
        f"[oikos.header]Rooms[/]      {rooms_str}",
        separator,
    ]

    logo_text = Text(_LOGO, style="oikos.primary")
    info_text = Text.from_markup("\n".join(lines))

    cols = Columns([logo_text, info_text], padding=(0, 3))
    panel = Panel(cols, border_style="oikos.border", box=box.DOUBLE, padding=(1, 2))
    console.print(panel)

    # Color bars
    _PALETTE = ["#FFB000", "#D4A017", "#8B6914", "#453510", "#FF8C00", "#FF4500", "#1A1205", "#0D0D0D"]
    bar = Text()
    for color in _PALETTE:
        bar.append("\u2588" * 5, style=color)
    console.print(bar)
    console.print("[oikos.dim]The home for AI agents.[/]")
