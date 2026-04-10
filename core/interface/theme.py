"""oikOS Rich theme — multi-variant phosphor terminal palette."""

from __future__ import annotations

import sys

from rich.console import Console
from rich.theme import Theme

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

THEME_VARIANTS: dict[str, dict[str, str]] = {
    "amber": {
        "primary": "#D4A017",
        "bright": "#FFB000",
        "dim": "#8B6914",
        "faint": "#453510",
    },
    "green": {
        "primary": "#33FF33",
        "bright": "#66FF66",
        "dim": "#1A8C1A",
        "faint": "#0D4D0D",
    },
    "white": {
        "primary": "#E0E0E0",
        "bright": "#FFFFFF",
        "dim": "#808080",
        "faint": "#404040",
    },
}


def build_theme(variant: str = "amber") -> Theme:
    """Build a Rich Theme from a named variant."""
    v = THEME_VARIANTS.get(variant, THEME_VARIANTS["amber"])
    return Theme(
        {
            "oikos.primary": v["primary"],
            "oikos.bright": v["bright"],
            "oikos.dim": v["dim"],
            "oikos.faint": v["faint"],
            "oikos.header": f"bold {v['primary']}",
            "oikos.border": v["dim"],
            "oikos.success": f"bold {v['bright']}",
            "oikos.warning": "bold #FF8C00",
            "oikos.error": "bold #FF4500",
            "oikos.system": f"italic {v['dim']}",
            "oikos.input": f"bold {v['bright']}",
        }
    )


def get_active_theme_name() -> str:
    """Read the active theme name from settings, default amber."""
    try:
        from core.interface.settings import get_setting

        name = get_setting("theme")
        return name if name in THEME_VARIANTS else "amber"
    except Exception:
        return "amber"


_active_variant_override: str | None = None

OIKOS_THEME = build_theme(get_active_theme_name())
console = Console(force_terminal=True, theme=OIKOS_THEME)


def apply_theme(variant: str) -> None:
    """Apply a theme variant to the global console (session override)."""
    global _active_variant_override
    _active_variant_override = variant
    console._theme = build_theme(variant)


def get_effective_theme_name() -> str:
    """Return the effective theme: session override > settings > default."""
    return _active_variant_override or get_active_theme_name()


def render_banner(target: Console | None = None) -> None:
    """Render the oikOS ASCII banner with gradient from active theme."""
    import pyfiglet

    c = target or console
    variant = get_effective_theme_name()
    v = THEME_VARIANTS.get(variant, THEME_VARIANTS["amber"])

    banner = pyfiglet.figlet_format("oikOS", font="slant")
    lines = [ln for ln in banner.rstrip("\n").split("\n") if ln.strip()]

    dim_hex = v["dim"].lstrip("#")
    bright_hex = v["bright"].lstrip("#")
    r0, g0, b0 = int(dim_hex[0:2], 16), int(dim_hex[2:4], 16), int(dim_hex[4:6], 16)
    r1, g1, b1 = int(bright_hex[0:2], 16), int(bright_hex[2:4], 16), int(bright_hex[4:6], 16)

    n = max(len(lines) - 1, 1)
    for i, line in enumerate(lines):
        ratio = i / n
        r = int(r0 + (r1 - r0) * ratio)
        g = int(g0 + (g1 - g0) * ratio)
        b = int(b0 + (b1 - b0) * ratio)
        c.print(line, style=f"bold #{r:02x}{g:02x}{b:02x}", highlight=False)
