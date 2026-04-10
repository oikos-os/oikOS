"""@oikos_tool decorator — registers functions with metadata for the Agent Framework.

The decorator stores metadata on the function and adds it to a global registry.
The original function remains directly callable without MCP overhead.
"""

from __future__ import annotations

import functools
import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable

from core.interface.models import ActionClass, DataTier

log = logging.getLogger(__name__)

# Re-export existing enums under framework-friendly names
PrivacyTier = DataTier
AutonomyLevel = ActionClass


class ToolTier(str, Enum):
    """Tool loading tier — controls when full schema is sent to the model."""
    CORE = "core"          # Always loaded, every Room, full schema
    ROOM = "room"          # Loaded if Room includes this toolset, full schema
    DEFERRED = "deferred"  # Name + description only, schema on demand


@dataclass(frozen=True)
class OikosToolMeta:
    """Metadata attached to an @oikos_tool-decorated function."""
    name: str
    description: str
    privacy: DataTier = DataTier.SAFE
    autonomy: ActionClass = ActionClass.SAFE
    toolset: str = "system"
    cost_category: str = "local"
    rate_limit: int = 0        # calls/min, 0 = unlimited
    token_ceiling: int = 0     # max input+output tokens, 0 = unlimited
    # T-109 Gate 1: concurrency and classification annotations
    concurrent_safe: bool = False   # Can run in parallel? (fail-closed default)
    read_only: bool = False         # Does it write? (fail-closed default)
    destructive: bool = False       # Is it irreversible?
    search_hint: str = ""           # Keywords for tool search scoring
    group: str = ""                 # Functional grouping
    tags: tuple[str, ...] = ()      # Cross-cutting tags
    # T-109 Gate 2: deferred loading tier
    tier: ToolTier = ToolTier.ROOM


# Global registry: name -> (function, metadata)
_REGISTRY: dict[str, tuple[Callable, OikosToolMeta]] = {}


def oikos_tool(
    name: str,
    description: str = "",
    privacy: DataTier = DataTier.SAFE,
    autonomy: ActionClass = ActionClass.SAFE,
    toolset: str = "system",
    cost_category: str = "local",
    rate_limit: int = 0,
    token_ceiling: int = 0,
    concurrent_safe: bool = False,
    read_only: bool = False,
    destructive: bool = False,
    search_hint: str = "",
    group: str = "",
    tags: list[str] | None = None,
    tier: ToolTier = ToolTier.ROOM,
) -> Callable:
    """Register a function as an oikOS tool with metadata.

    The function is returned unchanged — it remains directly callable.
    Registration happens at import time via the global _REGISTRY.
    """
    def decorator(fn: Callable) -> Callable:
        desc = description or fn.__doc__ or f"oikOS tool: {name}"
        meta = OikosToolMeta(
            name=name,
            description=desc,
            privacy=privacy,
            autonomy=autonomy,
            toolset=toolset,
            cost_category=cost_category,
            rate_limit=rate_limit,
            token_ceiling=token_ceiling,
            concurrent_safe=concurrent_safe,
            read_only=read_only,
            destructive=destructive,
            search_hint=search_hint,
            group=group,
            tags=tuple(tags) if tags else (),
            tier=tier,
        )

        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            return fn(*args, **kwargs)

        wrapper._oikos_meta = meta  # type: ignore[attr-defined]

        if name in _REGISTRY:
            log.warning("Tool '%s' already registered — overwriting", name)

        _REGISTRY[name] = (wrapper, meta)
        return wrapper

    return decorator


def get_registered_tools() -> dict[str, tuple[Callable, OikosToolMeta]]:
    """Return all registered oikos_tools."""
    return dict(_REGISTRY)


def clear_registry() -> None:
    """Clear the global tool registry. Used in tests."""
    _REGISTRY.clear()
