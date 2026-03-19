"""Cost tracking middleware — logs tool invocation costs."""

from __future__ import annotations

import time
from typing import Any, Callable

from core.framework.middleware.base import MiddlewareContext


class CostMiddleware:
    """Tracks tool invocation cost and latency via CostTracker."""

    def __init__(self, tracker=None):
        self._tracker = tracker

    async def __call__(self, ctx: MiddlewareContext, call_next: Callable) -> Any:
        t0 = time.monotonic()
        result = await call_next()
        latency_ms = int((time.monotonic() - t0) * 1000)

        if self._tracker:
            try:
                self._tracker.log_query(
                    provider=ctx.tool_meta.cost_category,
                    model=f"tool:{ctx.tool_name}",
                    input_tokens=0,
                    output_tokens=0,
                    latency_ms=latency_ms,
                )
            except Exception:
                pass  # Best-effort, never blocks

        return result
