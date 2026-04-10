"""Tool pool assembler — builds per-Room tool pools with deferred loading.

T-109 Gate 2 (R1): Assembles full-schema and deferred tool lists based on
Room toolset configuration and tool tier annotations.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from core.framework.decorator import OikosToolMeta, ToolTier, get_registered_tools


@dataclass
class ToolPool:
    """Assembled tool pool for a Room."""
    full_schema_tools: list[OikosToolMeta] = field(default_factory=list)
    deferred_tools: list[OikosToolMeta] = field(default_factory=list)
    total_count: int = 0


def assemble_tool_pool(allowed_toolsets: list[str] | None = None) -> ToolPool:
    """Assemble the tool pool for a Room.

    Args:
        allowed_toolsets: List of toolset names the Room includes.
            None means all toolsets (backward compat — all tools get full schema).

    Returns:
        ToolPool with full_schema_tools and deferred_tools.
    """
    registry = get_registered_tools()

    full_schema: list[OikosToolMeta] = []
    deferred: list[OikosToolMeta] = []

    for _name, (_fn, meta) in registry.items():
        if meta.tier == ToolTier.CORE:
            full_schema.append(meta)
        elif allowed_toolsets is None:
            # All toolsets allowed — everything gets full schema
            full_schema.append(meta)
        elif meta.toolset in allowed_toolsets:
            full_schema.append(meta)
        else:
            deferred.append(meta)

    return ToolPool(
        full_schema_tools=full_schema,
        deferred_tools=deferred,
        total_count=len(full_schema) + len(deferred),
    )


def render_deferred_listing(deferred_tools: list[OikosToolMeta]) -> str:
    """Render deferred tools as a compact listing for system prompt injection.

    Each tool costs ~5-10 tokens (vs 550-1,400 for full schema).
    """
    if not deferred_tools:
        return ""

    lines = ["## Additional Tools Available (use oikos_tool_search to load)"]
    for meta in sorted(deferred_tools, key=lambda m: m.name):
        lines.append(f"- {meta.name}: {meta.description} [{meta.group}]")
    return "\n".join(lines)
