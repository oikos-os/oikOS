"""Tests for T-109 Gate 1: tool concurrency partitioning."""

import asyncio
import time

import pytest
from core.framework.decorator import oikos_tool, clear_registry, get_registered_tools
from core.framework.concurrency import (
    ToolCall,
    ToolResult,
    execute_tool_batch,
    get_tool_metadata,
    MAX_TOOL_CONCURRENCY,
)


@pytest.fixture(autouse=True)
def clean_registry():
    clear_registry()
    yield
    clear_registry()


def _register_tools():
    """Register test tools for concurrency tests."""

    @oikos_tool(name="fast_read", concurrent_safe=True, read_only=True, search_hint="test", group="test")
    def fast_read(x: int = 0) -> dict:
        return {"value": x, "type": "read"}

    @oikos_tool(name="slow_read", concurrent_safe=True, read_only=True, search_hint="test", group="test")
    async def slow_read(x: int = 0) -> dict:
        await asyncio.sleep(0.05)
        return {"value": x, "type": "slow_read"}

    @oikos_tool(name="write_op", search_hint="test", group="test")
    def write_op(x: int = 0) -> dict:
        return {"value": x, "type": "write"}

    @oikos_tool(name="failing_read", concurrent_safe=True, read_only=True, search_hint="test", group="test")
    def failing_read(x: int = 0) -> dict:
        raise RuntimeError("simulated read failure")

    @oikos_tool(name="failing_write", search_hint="test", group="test")
    def failing_write(x: int = 0) -> dict:
        raise RuntimeError("simulated write failure")


class TestConcurrencyPartitioning:
    def test_empty_batch(self):
        results = asyncio.run(execute_tool_batch([]))
        assert results == []

    def test_read_only_tools_run(self):
        _register_tools()
        calls = [
            ToolCall(name="fast_read", arguments={"x": 1}),
            ToolCall(name="fast_read", arguments={"x": 2}),
        ]
        results = asyncio.run(execute_tool_batch(calls))
        assert len(results) == 2
        assert results[0].result["value"] == 1
        assert results[1].result["value"] == 2
        assert all(r.error is None for r in results)

    def test_write_tools_run_sequentially(self):
        _register_tools()
        calls = [
            ToolCall(name="write_op", arguments={"x": 10}),
            ToolCall(name="write_op", arguments={"x": 20}),
        ]
        results = asyncio.run(execute_tool_batch(calls))
        assert len(results) == 2
        assert results[0].result["value"] == 10
        assert results[1].result["value"] == 20

    def test_mixed_batch_preserves_order(self):
        _register_tools()
        calls = [
            ToolCall(name="fast_read", arguments={"x": 1}),
            ToolCall(name="write_op", arguments={"x": 2}),
            ToolCall(name="fast_read", arguments={"x": 3}),
        ]
        results = asyncio.run(execute_tool_batch(calls))
        assert len(results) == 3
        assert [r.result["value"] for r in results] == [1, 2, 3]

    def test_concurrent_reads_faster_than_sequential(self):
        """3 slow reads should run concurrently (~50ms) not sequentially (~150ms)."""
        _register_tools()
        calls = [ToolCall(name="slow_read", arguments={"x": i}) for i in range(3)]
        start = time.monotonic()
        results = asyncio.run(execute_tool_batch(calls))
        elapsed = time.monotonic() - start
        assert len(results) == 3
        # Concurrent: ~50ms. Sequential would be ~150ms. Allow some slack.
        assert elapsed < 0.12, f"Took {elapsed:.3f}s — expected concurrent execution"

    def test_failed_read_doesnt_crash_batch(self):
        _register_tools()
        calls = [
            ToolCall(name="fast_read", arguments={"x": 1}),
            ToolCall(name="failing_read", arguments={"x": 2}),
            ToolCall(name="fast_read", arguments={"x": 3}),
        ]
        results = asyncio.run(execute_tool_batch(calls))
        assert len(results) == 3
        assert results[0].error is None
        assert results[1].error is not None
        assert results[1].error == "Tool execution failed"
        assert results[2].error is None

    def test_failed_write_doesnt_crash_batch(self):
        _register_tools()
        calls = [
            ToolCall(name="write_op", arguments={"x": 1}),
            ToolCall(name="failing_write", arguments={"x": 2}),
            ToolCall(name="write_op", arguments={"x": 3}),
        ]
        results = asyncio.run(execute_tool_batch(calls))
        assert len(results) == 3
        assert results[0].error is None
        assert results[1].error is not None
        assert results[2].error is None

    def test_unknown_tool_returns_error(self):
        calls = [ToolCall(name="nonexistent_tool", arguments={})]
        results = asyncio.run(execute_tool_batch(calls))
        assert len(results) == 1
        assert results[0].error is not None
        assert results[0].error == "Tool execution failed"


class TestToolMetadata:
    def test_get_metadata_exists(self):
        _register_tools()
        meta = get_tool_metadata("fast_read")
        assert meta is not None
        assert meta.concurrent_safe is True
        assert meta.read_only is True

    def test_get_metadata_missing(self):
        assert get_tool_metadata("nonexistent") is None

    def test_max_concurrency_constant(self):
        assert MAX_TOOL_CONCURRENCY == 10


class TestConcurrencyBehavior:
    def test_reads_overlap_in_time(self):
        """Multiple concurrent reads execute overlapping, not sequentially."""
        timestamps: list[tuple[float, float]] = []

        @oikos_tool(name="timed_read", concurrent_safe=True, read_only=True, search_hint="t", group="t")
        async def timed_read(x: int = 0) -> dict:
            start = time.monotonic()
            await asyncio.sleep(0.05)
            end = time.monotonic()
            timestamps.append((start, end))
            return {"x": x}

        calls = [ToolCall(name="timed_read", arguments={"x": i}) for i in range(3)]
        asyncio.run(execute_tool_batch(calls))
        # If sequential, total > 0.15s. If concurrent, reads overlap.
        assert len(timestamps) == 3
        earliest_start = min(t[0] for t in timestamps)
        latest_start = max(t[0] for t in timestamps)
        assert latest_start - earliest_start < 0.04, "Reads should start near-simultaneously"

    def test_write_after_reads(self):
        """Write tools execute after all read tools complete."""
        order: list[str] = []

        @oikos_tool(name="ordering_read", concurrent_safe=True, read_only=True, search_hint="t", group="t")
        async def ordering_read(x: int = 0) -> dict:
            await asyncio.sleep(0.02)
            order.append("read")
            return {}

        @oikos_tool(name="ordering_write", search_hint="t", group="t")
        def ordering_write(x: int = 0) -> dict:
            order.append("write")
            return {}

        calls = [
            ToolCall(name="ordering_read", arguments={}),
            ToolCall(name="ordering_write", arguments={}),
            ToolCall(name="ordering_read", arguments={}),
        ]
        asyncio.run(execute_tool_batch(calls))
        # Both reads should complete before the write
        write_idx = order.index("write")
        assert order[:write_idx] == ["read", "read"]

    def test_mixed_batch_original_order(self):
        """Results returned in original request order regardless of execution order."""
        _register_tools()
        calls = [
            ToolCall(name="write_op", arguments={"x": 1}),
            ToolCall(name="fast_read", arguments={"x": 2}),
            ToolCall(name="write_op", arguments={"x": 3}),
        ]
        results = asyncio.run(execute_tool_batch(calls))
        assert results[0].result["value"] == 1
        assert results[1].result["value"] == 2
        assert results[2].result["value"] == 3

    def test_failed_read_write_still_runs(self):
        """A failing read doesn't prevent write tools from executing."""
        _register_tools()
        calls = [
            ToolCall(name="failing_read", arguments={}),
            ToolCall(name="write_op", arguments={"x": 99}),
        ]
        results = asyncio.run(execute_tool_batch(calls))
        assert results[0].error is not None
        assert results[1].result["value"] == 99

    def test_semaphore_caps_at_10(self):
        """With 11 concurrent reads, only 10 run simultaneously."""
        max_concurrent = 0
        current = 0
        lock = asyncio.Lock()

        @oikos_tool(name="counting_read", concurrent_safe=True, read_only=True, search_hint="t", group="t")
        async def counting_read(x: int = 0) -> dict:
            nonlocal max_concurrent, current
            async with lock:
                current += 1
                if current > max_concurrent:
                    max_concurrent = current
            await asyncio.sleep(0.02)
            async with lock:
                current -= 1
            return {}

        calls = [ToolCall(name="counting_read", arguments={"x": i}) for i in range(11)]
        asyncio.run(execute_tool_batch(calls))
        assert max_concurrent <= MAX_TOOL_CONCURRENCY

    def test_empty_batch_returns_empty(self):
        results = asyncio.run(execute_tool_batch([]))
        assert results == []
