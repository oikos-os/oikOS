"""oikOS thinking indicators — personality during inference."""

from __future__ import annotations

import random

THINKING_INDICATORS = [
    "\u25c8 consulting the vault...",
    "\u25c8 reasoning...",
    "\u25c8 composing response...",
    "\u25c8 searching memory...",
    "\u25c8 weighing options...",
    "\u25c8 connecting patterns...",
    "\u25c8 considering context...",
    "\u25c8 deliberating...",
]


def get_thinking_indicator() -> str:
    """Return a random thinking indicator string."""
    return random.choice(THINKING_INDICATORS)
