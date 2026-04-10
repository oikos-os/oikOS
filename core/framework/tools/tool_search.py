"""Tool search — oikos_tool_search MCP tool (T-109 Gate 2, tool #51).

Enables deferred tool loading: models can discover and load tool schemas
on demand instead of receiving all schemas upfront.
"""

from __future__ import annotations

import re

from core.framework.decorator import (
    oikos_tool,
    OikosToolMeta,
    ToolTier,
    PrivacyTier,
    AutonomyLevel,
    get_registered_tools,
)


def _score_tool(meta: OikosToolMeta, terms: list[str]) -> int:
    """Score a tool against search terms. Higher = better match.

    Weights: exact name (10) > toolset (8) > group (6) > hint (4) > description (2).
    Exact matches are exclusive (a term matching the name won't also score for
    toolset/group), but hint and description accumulate independently so
    well-annotated tools get credit across both fields.
    """
    score = 0
    for term in terms:
        tl = term.lower()
        pattern = re.compile(rf"\b{re.escape(term)}\b", re.IGNORECASE)
        if tl == meta.name.lower():
            score += 10
        elif tl == meta.toolset.lower():
            score += 8
        elif tl == meta.group.lower():
            score += 6
        else:
            if pattern.search(meta.search_hint):
                score += 4
            if pattern.search(meta.description):
                score += 2
    return score


def _meta_to_dict(meta: OikosToolMeta) -> dict:
    """Convert tool metadata to a serializable dict."""
    return {
        "name": meta.name,
        "description": meta.description,
        "toolset": meta.toolset,
        "group": meta.group,
        "concurrent_safe": meta.concurrent_safe,
        "read_only": meta.read_only,
        "destructive": meta.destructive,
        "tier": meta.tier.value,
        "tags": list(meta.tags),
    }


@oikos_tool(
    name="oikos_tool_search",
    description="Search for additional tools not currently loaded. Use when you need a capability not in your active toolset.",
    toolset="system",
    tier=ToolTier.CORE,
    concurrent_safe=True,
    read_only=True,
    search_hint="find tools capabilities search discover load additional",
    group="system",
)
def tool_search(query: str, max_results: int = 5) -> dict:
    """Search the full tool registry and return matching tool schemas.

    Supports two modes:
    - "select:tool_name" or "select:tool1,tool2" — exact match, returns full metadata
    - keyword search — scored ranking, returns top matches
    """
    registry = get_registered_tools()

    # Exact selection bypasses scoring — callers already know the tool name
    if query.startswith("select:"):
        names = [n.strip() for n in query[7:].split(",") if n.strip()]
        matches = []
        for name in names:
            entry = registry.get(name)
            if entry:
                matches.append(_meta_to_dict(entry[1]))
        return {"matches": matches, "count": len(matches), "mode": "select"}

    terms = query.split()
    if not terms:
        return {"matches": [], "count": 0, "mode": "search"}

    scored: list[tuple[int, OikosToolMeta]] = []
    for _name, (_fn, meta) in registry.items():
        s = _score_tool(meta, terms)
        if s > 0:
            scored.append((s, meta))

    scored.sort(key=lambda x: x[0], reverse=True)
    top = scored[:max_results]

    return {
        "matches": [_meta_to_dict(meta) for _, meta in top],
        "count": len(top),
        "mode": "search",
    }
