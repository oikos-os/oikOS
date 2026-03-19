"""oikOS Rich theme — amber phosphor terminal palette."""

from __future__ import annotations

import sys

from rich.console import Console
from rich.theme import Theme

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

OIKOS_THEME = Theme(
    {
        "oikos.primary": "#D4A017",
        "oikos.bright": "#FFB000",
        "oikos.dim": "#8B6914",
        "oikos.faint": "#453510",
        "oikos.header": "bold #D4A017",
        "oikos.border": "#8B6914",
        "oikos.success": "bold #FFB000",
        "oikos.warning": "bold #FF8C00",
        "oikos.error": "bold #FF4500",
        "oikos.system": "italic #8B6914",
        "oikos.input": "bold #FFD700",
    }
)

console = Console(force_terminal=True, theme=OIKOS_THEME)


def render_banner(target: Console | None = None) -> None:
    """Render the oikOS ASCII banner with amber gradient."""
    import pyfiglet

    c = target or console
    banner = pyfiglet.figlet_format("oikOS", font="slant")
    lines = [ln for ln in banner.rstrip("\n").split("\n") if ln.strip()]
    n = max(len(lines) - 1, 1)
    for i, line in enumerate(lines):
        ratio = i / n
        r = int(139 + (255 - 139) * ratio)  # #8B → #FF
        g = int(105 + (176 - 105) * ratio)  # #69 → #B0
        b = int(20 + (0 - 20) * ratio)  # #14 → #00
        c.print(line, style=f"bold #{r:02x}{g:02x}{b:02x}", highlight=False)
