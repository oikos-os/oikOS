"""Rate limiting middleware — sliding window per-tool limiter."""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import Any, Callable

from core.framework.exceptions import RateLimitExceeded
from core.framework.middleware.base import MiddlewareContext


class RateLimitMiddleware:
    """Per-tool, per-client sliding-window rate limiter.

    Thread-safe via threading.Lock. In-memory only (resets on restart).
    """

    def __init__(self, default_limit: int = 60):
        self._default_limit = default_limit
        self._windows: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    async def __call__(self, ctx: MiddlewareContext, call_next: Callable) -> Any:
        # rate_limit=0 means explicitly unlimited for this tool
        if ctx.tool_meta.rate_limit == 0:
            return await call_next()
        limit = ctx.tool_meta.rate_limit or self._default_limit

        key = f"{ctx.tool_name}:{ctx.client_id or 'default'}"
        now = time.monotonic()
        window_start = now - 60.0

        with self._lock:
            if key not in self._windows:
                self._windows[key] = deque()
            q = self._windows[key]

            # Prune expired entries
            while q and q[0] < window_start:
                q.popleft()

            if len(q) >= limit:
                retry_after = 60.0 - (now - q[0]) if q else 60.0
                raise RateLimitExceeded(ctx.tool_name, retry_after)

            q.append(now)

        return await call_next()
