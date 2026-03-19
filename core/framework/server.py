"""OikosServer — composes FastMCP with the oikOS middleware chain.

Wraps a FastMCP instance. At startup, reads the global tool registry,
builds middleware-wrapped functions, and registers them via FastMCP.add_tool().
"""

from __future__ import annotations

import asyncio
import functools
import inspect
import logging
from typing import Any, Callable

from core.framework.decorator import OikosToolMeta, get_registered_tools
from core.framework.middleware.base import MiddlewareContext

log = logging.getLogger(__name__)


class OikosServer:
    """MCP server with privacy, autonomy, cost, and audit middleware.

    Uses composition over inheritance — owns a FastMCP instance internally.
    """

    def __init__(
        self,
        name: str = "oikos",
        middleware: list | None = None,
        **fastmcp_kwargs,
    ):
        from mcp.server.fastmcp import FastMCP
        self._mcp = FastMCP(name=name, **fastmcp_kwargs)
        self._middleware = middleware if middleware is not None else self._default_middleware()
        self._ensure_mandatory_middleware()
        self._registered = False
        self._transport = "stdio"  # default, updated by run()

    @staticmethod
    def _default_middleware() -> list:
        from core.framework.middleware.auth import AuthMiddleware
        from core.framework.middleware.privacy import PrivacyMiddleware
        from core.framework.middleware.autonomy import AutonomyMiddleware
        from core.framework.middleware.rate_limit import RateLimitMiddleware
        from core.framework.middleware.cost import CostMiddleware
        from core.framework.middleware.audit import AuditMiddleware
        from core.framework.middleware.error_handler import ErrorHandlerMiddleware
        return [
            AuthMiddleware(),
            ErrorHandlerMiddleware(),
            PrivacyMiddleware(),
            AutonomyMiddleware(),
            RateLimitMiddleware(),
            CostMiddleware(),
            AuditMiddleware(),
        ]

    def _ensure_mandatory_middleware(self) -> None:
        """Privacy and Audit middleware cannot be removed. Enforce their presence."""
        from core.framework.middleware.privacy import PrivacyMiddleware
        from core.framework.middleware.audit import AuditMiddleware

        has_privacy = any(isinstance(m, PrivacyMiddleware) for m in self._middleware)
        has_audit = any(isinstance(m, AuditMiddleware) for m in self._middleware)

        if not has_privacy:
            self._middleware.insert(0, PrivacyMiddleware())
        if not has_audit:
            self._middleware.append(AuditMiddleware())

    def register_tools(self, toolset: str | None = None, tools: list[str] | None = None) -> int:
        """Register oikos_tools with FastMCP, wrapped in middleware.

        Args:
            toolset: Only register tools in this toolset (e.g., "vault").
            tools: Only register these specific tool names.

        Returns:
            Number of tools registered.
        """
        registry = get_registered_tools()
        count = 0

        for name, (fn, meta) in registry.items():
            if toolset and meta.toolset != toolset:
                continue
            if tools and name not in tools:
                continue

            wrapper = self._build_wrapper(fn, meta)
            self._mcp.add_tool(wrapper, name=meta.name, description=meta.description)
            count += 1
            log.debug("Registered MCP tool: %s (toolset=%s)", meta.name, meta.toolset)

        self._registered = True
        log.info("Registered %d MCP tools", count)
        return count

    def _build_wrapper(self, fn: Callable, meta: OikosToolMeta) -> Callable:
        """Create an async wrapper that runs fn through the middleware chain."""

        server = self  # capture for closure

        @functools.wraps(fn)
        async def wrapper(**kwargs: Any) -> Any:
            ctx = MiddlewareContext(
                tool_name=meta.name,
                tool_meta=meta,
                arguments=kwargs,
                extras={"transport": server._transport},
            )
            return await server._run_chain(list(server._middleware), ctx, fn, kwargs)

        return wrapper

    async def _run_chain(
        self,
        middleware: list,
        ctx: MiddlewareContext,
        fn: Callable,
        kwargs: dict,
    ) -> Any:
        """Recursively execute middleware chain, then the tool function."""
        if not middleware:
            # End of chain — execute the actual tool
            result = fn(**kwargs)
            if inspect.isawaitable(result):
                return await result
            return result

        current = middleware[0]
        remaining = middleware[1:]

        async def call_next() -> Any:
            return await self._run_chain(remaining, ctx, fn, ctx.arguments)

        return await current(ctx, call_next)

    def run(self, transport: str = "stdio", **kwargs) -> None:
        """Start the MCP server with the specified transport."""
        self._transport = transport
        if not self._registered:
            self.register_tools()
        self._mcp.run(transport=transport)

    @property
    def mcp(self):
        """Access the underlying FastMCP instance for advanced use."""
        return self._mcp
