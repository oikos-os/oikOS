"""Toolset constants and registry filtering for the oikOS Agent Framework."""

from __future__ import annotations

# Toolset identifiers — tools are grouped by function
VAULT = "vault"
BROWSER = "browser"
RESEARCH = "research"
SYSTEM = "system"
FILE = "file"
ORACLE = "oracle"

ALL_TOOLSETS = {VAULT, BROWSER, RESEARCH, SYSTEM, FILE, ORACLE}


def get_tools_by_toolset(toolset: str) -> list[tuple]:
    """Return registered tools matching the given toolset.

    Returns list of (function, OikosToolMeta) tuples.
    """
    from core.framework.decorator import get_registered_tools
    return [
        (fn, meta) for fn, meta in get_registered_tools().values()
        if meta.toolset == toolset
    ]
