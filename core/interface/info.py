"""oikOS info — neofetch-style system overview."""

from __future__ import annotations

from rich import box
from rich.columns import Columns
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

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

    # Active room
    try:
        from core.rooms.manager import get_room_manager

        room_name = get_room_manager().get_active_room().name
    except Exception:
        room_name = "home"

    # Inference model
    try:
        from core.cognition.inference import check_inference_model
        from core.interface.config import INFERENCE_MODEL

        model = INFERENCE_MODEL if check_inference_model() else "offline"
    except Exception:
        model = "unknown"

    # Credits
    try:
        from core.safety.credits import load_credits

        cred = load_credits()
        credits_str = f"{cred.used}/{cred.monthly_cap}"
    except Exception:
        credits_str = "N/A"

    # FSM state
    try:
        from core.autonomic.fsm import get_current_state

        fsm = get_current_state().value.upper()
    except Exception:
        fsm = "UNKNOWN"

    # Backend
    try:
        from core.cognition.providers.bootstrap import get_provider_registry

        reg = get_provider_registry()
        backend = reg.get_default_name()
    except Exception:
        backend = "unknown"

    # Tool count from live registry
    try:
        from core.framework.decorator import get_registered_tools

        _reg = get_registered_tools()
        _toolsets = {m.toolset for _, m in _reg.values() if m.toolset}
        tools_str = f"{len(_reg)} across {len(_toolsets)} toolsets"
    except Exception:
        tools_str = "unavailable"

    separator = "[oikos.dim]────────────────────────[/]"
    lines = [
        separator,
        f"[oikos.header]OS[/]         oikOS v{__version__}",
        f"[oikos.header]Room[/]       {room_name}",
        f"[oikos.header]Model[/]      {model}",
        f"[oikos.header]Vault[/]      {vault_str}",
        f"[oikos.header]Tools[/]      {tools_str}",
        f"[oikos.header]Credits[/]    {credits_str}",
        f"[oikos.header]FSM[/]        {fsm}",
        f"[oikos.header]Backend[/]    {backend}",
        f"[oikos.header]Privacy[/]    NEVER_LEAVE enforced",
        separator,
        "[oikos.system]The home for AI agents.[/]",
    ]

    logo_text = Text(_LOGO, style="oikos.primary")
    info_text = Text.from_markup("\n".join(lines))

    cols = Columns([logo_text, info_text], padding=(0, 3))
    panel = Panel(cols, border_style="oikos.border", box=box.DOUBLE, padding=(1, 2))
    console.print(panel)
