"""oikOS logo renderer — house mark + wordmark as Rich Text objects.

House mark: 16×14 pixel grid rendered via half-block characters (▀▄█) for
2× vertical resolution. Each terminal row encodes two pixel rows.
Wordmark: hardcoded ansi_shadow pyfiglet output, oik/OS two-tone coloring.
"""
from rich.text import Text

# Amber palette (faint → peak)
C_FAINT  = "#453510"
C_DIM    = "#6B5012"
C_MID    = "#8B6914"
C_AMBER  = "#D4A017"
C_BRIGHT = "#FFB000"
C_PEAK   = "#FFE8B0"

# High-resolution house mark: 16 columns × 14 rows (pairs → 7 terminal rows)
_HOUSE_GRID = [
    # Pair 0 — apex (wider tip)
    [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],
    [0,0,0,0,0,1,1,1,1,1,1,0,0,0,0,0],
    # Pair 1 — upper roof
    [0,0,0,0,1,1,1,1,1,1,1,1,0,0,0,0],
    [0,0,0,1,1,1,1,1,1,1,1,1,1,0,0,0],
    # Pair 2 — lower roof / eaves
    [0,0,1,1,1,1,1,1,1,1,1,1,1,1,0,0],
    [0,1,1,1,1,1,1,1,1,1,1,1,1,1,1,0],
    # Pair 3 — wall (full width)
    [1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1],
    [1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1],
    # Pair 4 — the eyes
    [1,1,1,1,0,0,1,1,1,1,0,0,1,1,1,1],
    [1,1,1,1,0,0,1,1,1,1,0,0,1,1,1,1],
    # Pair 5 — below eyes
    [1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1],
    [1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1],
    # Pair 6 — base
    [1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1],
    [1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1],
]

# Color per pixel row — gradient from faint apex to bright eyes
_ROW_COLORS = [
    None,      C_FAINT,   # pair 0: apex
    C_FAINT,   C_DIM,     # pair 1: upper roof
    C_DIM,     C_MID,     # pair 2: lower roof
    C_MID,     C_MID,     # pair 3: wall
    C_AMBER,   C_AMBER,   # pair 4: eyes (warmest)
    C_MID,     C_MID,     # pair 5: below eyes
    C_DIM,     C_DIM,     # pair 6: base
]

# Hardcoded ansi_shadow wordmark for "oikOS" — never changes, no runtime pyfiglet.
# Split into (oik_part, OS_part) per line. Column split is after the 'k' glyph.
_WORDMARK_LINES = [
    (" ██████╗ ██╗██╗  ██╗",  " ██████╗ ███████╗"),
    ("██╔═══██╗██║██║ ██╔╝", "██╔═══██╗██╔════╝"),
    ("██║   ██║██║█████╔╝ ", "██║   ██║███████╗"),
    ("██║   ██║██║██╔═██╗ ", "██║   ██║╚════██║"),
    ("╚██████╔╝██║██║  ██╗", "╚██████╔╝███████║"),
    (" ╚═════╝ ╚═╝╚═╝  ╚═╝", " ╚═════╝ ╚══════╝"),
]

# Per-line color pairs: (oik_color, OS_color)
_WORDMARK_COLORS = [
    (C_FAINT,  C_AMBER),
    (C_MID,    C_BRIGHT),
    (C_AMBER,  C_PEAK),    # center glow
    (C_MID,    C_BRIGHT),
    (C_FAINT,  C_AMBER),
    (C_FAINT,  C_MID),
]


def render_house_mark() -> list[str]:
    """Return 7 plain strings using half-block characters."""
    result = []
    for pair in range(7):
        top_row = _HOUSE_GRID[pair * 2]
        bot_row = _HOUSE_GRID[pair * 2 + 1]
        chars = []
        for col in range(16):
            top, bot = top_row[col], bot_row[col]
            if top and bot:
                chars.append("\u2588")
            elif top:
                chars.append("\u2580")
            elif bot:
                chars.append("\u2584")
            else:
                chars.append(" ")
        result.append("".join(chars))
    return result


def render_house_mark_rich() -> list[Text]:
    """Return 7 Rich Text objects with half-block rendering and per-row gradient."""
    result = []
    for pair in range(7):
        top_row = _HOUSE_GRID[pair * 2]
        bot_row = _HOUSE_GRID[pair * 2 + 1]
        top_c = _ROW_COLORS[pair * 2]
        bot_c = _ROW_COLORS[pair * 2 + 1]
        line = Text()
        for col in range(16):
            top, bot = top_row[col], bot_row[col]
            if top and bot:
                if top_c == bot_c:
                    line.append("\u2588", style=top_c or "")
                else:
                    line.append("\u2580", style=f"{top_c} on {bot_c}")
            elif top:
                line.append("\u2580", style=top_c or "")
            elif bot:
                line.append("\u2584", style=bot_c or "")
            else:
                line.append(" ")
        result.append(line)
    return result


def render_wordmark() -> list[Text]:
    """Return 6 Rich Text objects with oik/OS two-tone coloring."""
    result = []
    for (oik, os_part), (oik_color, os_color) in zip(_WORDMARK_LINES, _WORDMARK_COLORS):
        line = Text()
        line.append(oik, style=oik_color)
        line.append(os_part, style=os_color)
        result.append(line)
    return result


def render_logo_text() -> Text:
    """Compose house mark + wordmark into a single Rich Text, bottom-aligned.

    House row 0 sits above the wordmark (solo line).
    House rows 1-6 align with wordmark lines 1-6, separated by a 2-char gap.
    """
    house_lines = render_house_mark_rich()
    word_lines = render_wordmark()

    logo = Text()

    # Row 0 — apex, no wordmark alongside it
    logo.append_text(house_lines[0])
    logo.append("\n")

    # Rows 1-6 — paired with wordmark lines (2-char gap between)
    for house_line, word_line in zip(house_lines[1:], word_lines):
        logo.append_text(house_line)
        logo.append("  ")
        logo.append_text(word_line)
        logo.append("\n")

    return logo
