"""Authentication middleware — validates OIKOS_API_KEY."""

from __future__ import annotations

import os
from typing import Any, Callable

from core.framework.middleware.base import MiddlewareContext


class AuthMiddleware:
    """Validates API key from client context. Passes through if no key configured."""

    async def __call__(self, ctx: MiddlewareContext, call_next: Callable) -> Any:
        expected = os.environ.get("OIKOS_API_KEY")
        if not expected:
            return await call_next()

        client_key = ctx.extras.get("api_key")
        if not client_key or client_key != expected:
            raise PermissionError("Invalid or missing API key")

        return await call_next()
