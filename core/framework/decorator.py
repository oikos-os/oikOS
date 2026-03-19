"""@oikos_tool decorator — registers functions with metadata for the Agent Framework.

The decorator stores metadata on the function and adds it to a global registry.
The original function remains directly callable without MCP overhead.
"""

from __future__ import annotations

import functools
import logging
from dataclasses import dataclass, field
from typing import Any, Callable

from core.interface.models import ActionClass, DataTier

log = logging.getLogger(__name__)

# Re-export existing enums under framework-friendly names
PrivacyTier = DataTier
AutonomyLevel = ActionClass


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
        )

        if name in _REGISTRY:
            log.warning("Tool '%s' already registered — overwriting", name)

        _REGISTRY[name] = (fn, meta)
        fn._oikos_meta = meta  # type: ignore[attr-defined]

        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            return fn(*args, **kwargs)

        wrapper._oikos_meta = meta  # type: ignore[attr-defined]
        return wrapper

    return decorator


def get_registered_tools() -> dict[str, tuple[Callable, OikosToolMeta]]:
    """Return all registered oikos_tools."""
    return dict(_REGISTRY)


def clear_registry() -> None:
    """Clear the global tool registry. Used in tests."""
    _REGISTRY.clear()
