"""Tests for rate limiting middleware."""

import asyncio
import pytest

from core.framework.middleware.rate_limit import RateLimitMiddleware
from core.framework.middleware.base import MiddlewareContext
from core.framework.decorator import OikosToolMeta
from core.framework.exceptions import RateLimitExceeded


def _make_ctx(rate_limit=5, tool_name="test", client_id=None):
    return MiddlewareContext(
        tool_name=tool_name,
        tool_meta=OikosToolMeta(name=tool_name, description="test", rate_limit=rate_limit),
        arguments={},
        client_id=client_id,
    )


async def _noop():
    return "ok"


class TestRateLimitMiddleware:
    def test_under_limit_passes(self):
        mw = RateLimitMiddleware()
        ctx = _make_ctx(rate_limit=10)
        result = asyncio.get_event_loop().run_until_complete(mw(ctx, _noop))
        assert result == "ok"

    def test_at_limit_raises(self):
        mw = RateLimitMiddleware()
        for _ in range(5):
            ctx = _make_ctx(rate_limit=5)
            asyncio.get_event_loop().run_until_complete(mw(ctx, _noop))

        ctx = _make_ctx(rate_limit=5)
        with pytest.raises(RateLimitExceeded):
            asyncio.get_event_loop().run_until_complete(mw(ctx, _noop))

    def test_no_limit_tool_always_passes(self):
        mw = RateLimitMiddleware()
        for _ in range(100):
            ctx = _make_ctx(rate_limit=0)
            asyncio.get_event_loop().run_until_complete(mw(ctx, _noop))
        # No exception = pass

    def test_different_tools_independent(self):
        mw = RateLimitMiddleware()
        for _ in range(5):
            ctx = _make_ctx(rate_limit=5, tool_name="tool_a")
            asyncio.get_event_loop().run_until_complete(mw(ctx, _noop))

        # tool_b should still be under limit
        ctx = _make_ctx(rate_limit=5, tool_name="tool_b")
        result = asyncio.get_event_loop().run_until_complete(mw(ctx, _noop))
        assert result == "ok"

    def test_different_clients_independent(self):
        mw = RateLimitMiddleware()
        for _ in range(5):
            ctx = _make_ctx(rate_limit=5, client_id="client_a")
            asyncio.get_event_loop().run_until_complete(mw(ctx, _noop))

        ctx = _make_ctx(rate_limit=5, client_id="client_b")
        result = asyncio.get_event_loop().run_until_complete(mw(ctx, _noop))
        assert result == "ok"

    def test_retry_after_is_positive(self):
        mw = RateLimitMiddleware()
        for _ in range(3):
            ctx = _make_ctx(rate_limit=3)
            asyncio.get_event_loop().run_until_complete(mw(ctx, _noop))

        ctx = _make_ctx(rate_limit=3)
        with pytest.raises(RateLimitExceeded) as exc_info:
            asyncio.get_event_loop().run_until_complete(mw(ctx, _noop))
        assert exc_info.value.retry_after > 0
