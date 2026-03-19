"""oikOS boot sequence — phosphor terminal startup animation."""

from __future__ import annotations

import random
import time

from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn


def _get_tool_counts() -> tuple[int, int]:
    """Return (tool_count, toolset_count) from the live registry."""
    try:
        from core.framework.decorator import get_registered_tools

        registry = get_registered_tools()
        toolsets = {meta.toolset for _, meta in registry.values() if meta.toolset}
        return len(registry), len(toolsets)
    except Exception:
        return 0, 0


def run_boot_sequence(console: Console, *, port: int = 8420, dev: bool = False) -> None:
    """Execute the phosphor boot animation before server start."""
    from core import __version__

    console.clear()

    _typewriter(console, f"oikOS BIOS v{__version__} — Phosphor Systems")
    time.sleep(0.3)

    try:
        from core.memory.indexer import get_table_stats

        stats = get_table_stats()
        chunk_count = stats["total_rows"]
        file_count = stats["unique_files"]
    except Exception:
        chunk_count, file_count = 0, 0

    _count_up(console, "Memory", chunk_count, suffix="chunks indexed")
    time.sleep(0.2)

    from core.interface.theme import render_banner

    render_banner(console)
    time.sleep(0.3)

    _module_load(console)
    time.sleep(0.2)

    _system_panel(console, port=port, dev=dev, file_count=file_count)


def _typewriter(console: Console, text: str, delay: float = 0.025) -> None:
    """Print text character-by-character with jitter."""
    for ch in text:
        console.print(ch, end="", style="oikos.dim", highlight=False)
        time.sleep(delay + random.uniform(0, 0.015))
    console.print()


def _count_up(console: Console, label: str, target: int, *, suffix: str = "") -> None:
    """Overwrite-in-place counter — Rich ignores \\r so we use file handle directly."""
    stream = console.file
    steps = min(target, 16)
    for i in range(steps + 1):
        val = int(target * i / max(steps, 1))
        stream.write(f"\r  {label}: {val} {suffix}")
        stream.flush()
        time.sleep(0.03)
    stream.write("\r" + " " * 60 + "\r")  # clear line
    stream.flush()
    console.print(f"  {label}: {target} {suffix}", style="oikos.primary")


def _module_load(console: Console) -> None:
    """Show module loading with amber progress bars."""
    modules = ["VAULT", "IDENTITY", "SAFETY", "COGNITION", "AGENCY", "FRAMEWORK"]
    with Progress(
        SpinnerColumn("dots", style="oikos.primary"),
        TextColumn("[oikos.primary]{task.description}"),
        BarColumn(complete_style="oikos.primary", finished_style="oikos.dim"),
        TextColumn("[oikos.dim]{task.percentage:>3.0f}%"),
        console=console,
    ) as progress:
        for mod in modules:
            task = progress.add_task(f"Loading {mod}...", total=100)
            steps = random.randint(6, 12)
            for _ in range(steps):
                progress.update(task, advance=random.uniform(5, 18))
                time.sleep(random.uniform(0.02, 0.06))
            progress.update(task, completed=100)


def _system_panel(
    console: Console, *, port: int, dev: bool, file_count: int
) -> None:
    """Render the final system-ready panel with real values."""
    from core import __version__

    try:
        from core.rooms.manager import get_room_manager

        room_name = get_room_manager().get_active_room().name
    except Exception:
        room_name = "home"

    tool_count, toolset_count = _get_tool_counts()
    mode = "DEV" if dev else "PROD"
    lines = [
        f"[oikos.bright]◈ oikOS v{__version__} initialized ◈[/]",
        "",
        f"  [oikos.dim]Vault:[/]   {file_count} files",
        f"  [oikos.dim]Tools:[/]   {tool_count} across {toolset_count} toolsets",
        f"  [oikos.dim]Room:[/]    {room_name}",
        f"  [oikos.dim]Mode:[/]    {mode}",
        "",
        "  [oikos.system]Intelligence is cheap.[/]",
        "  [oikos.system]Context is expensive.[/]",
        "  [oikos.system]Build for context.[/]",
    ]

    panel = Panel(
        "\n".join(lines),
        border_style="oikos.border",
        box=box.DOUBLE,
        padding=(1, 2),
    )
    console.print(panel)
    console.print(f"  [oikos.bright]⌂[/] http://127.0.0.1:{port}")
