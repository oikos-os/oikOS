"""Middleware base types for the oikOS Agent Framework."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Protocol, runtime_checkable

from core.framework.decorator import OikosToolMeta


@dataclass
class MiddlewareContext:
    """Mutable context passed through the middleware chain."""
    tool_name: str
    tool_meta: OikosToolMeta
    arguments: dict[str, Any]
    client_id: str | None = None
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    result: Any = None
    error: Exception | None = None
    extras: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class Middleware(Protocol):
    """Protocol for middleware in the oikOS tool chain."""

    async def __call__(self, ctx: MiddlewareContext, call_next: Callable) -> Any:
        ...
