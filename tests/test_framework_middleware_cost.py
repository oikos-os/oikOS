"""Tests for cost tracking middleware."""

import asyncio
import pytest
from unittest.mock import MagicMock

from core.framework.middleware.cost import CostMiddleware
from core.framework.middleware.base import MiddlewareContext
from core.framework.decorator import OikosToolMeta


def _make_ctx():
    return MiddlewareContext(
        tool_name="test_tool",
        tool_meta=OikosToolMeta(name="test_tool", description="test", cost_category="local"),
        arguments={},
    )


async def _noop():
    return "result"


class TestCostMiddleware:
    def test_logs_query(self):
        tracker = MagicMock()
        mw = CostMiddleware(tracker)
        ctx = _make_ctx()
        asyncio.get_event_loop().run_until_complete(mw(ctx, _noop))
        tracker.log_query.assert_called_once()
        call_kwargs = tracker.log_query.call_args[1]
        assert call_kwargs["provider"] == "local"
        assert call_kwargs["model"] == "tool:test_tool"
        assert call_kwargs["latency_ms"] >= 0

    def test_no_tracker_passes(self):
        mw = CostMiddleware(tracker=None)
        ctx = _make_ctx()
        result = asyncio.get_event_loop().run_until_complete(mw(ctx, _noop))
        assert result == "result"

    def test_tracker_error_does_not_crash(self):
        tracker = MagicMock()
        tracker.log_query.side_effect = RuntimeError("disk full")
        mw = CostMiddleware(tracker)
        ctx = _make_ctx()
        result = asyncio.get_event_loop().run_until_complete(mw(ctx, _noop))
        assert result == "result"

    def test_returns_result(self):
        tracker = MagicMock()
        mw = CostMiddleware(tracker)
        ctx = _make_ctx()

        async def return_data():
            return {"key": "value"}

        result = asyncio.get_event_loop().run_until_complete(mw(ctx, return_data))
        assert result == {"key": "value"}
