"""Tool concurrency partitioning — run read-only tools in parallel, writes sequentially.

T-109 Gate 1 (R3): Implements partitioning of tool call batches based on
concurrent_safe and read_only annotations from @oikos_tool.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
from dataclasses import dataclass
from typing import Any

from core.framework.decorator import OikosToolMeta, get_registered_tools

log = logging.getLogger(__name__)

MAX_TOOL_CONCURRENCY = 10


@dataclass
class ToolCall:
    """A single tool invocation request."""
    name: str
    arguments: dict[str, Any]


@dataclass
class ToolResult:
    """Result from a single tool invocation."""
    name: str
    result: Any = None
    error: str | None = None


def get_tool_metadata(tool_name: str) -> OikosToolMeta | None:
    """Look up metadata for a registered tool by name."""
    registry = get_registered_tools()
    entry = registry.get(tool_name)
    if entry is None:
        return None
    return entry[1]


def _is_concurrently_runnable(meta: OikosToolMeta | None) -> bool:
    """Check if a tool can safely run concurrently (fail-closed)."""
    if meta is None:
        return False
    return meta.concurrent_safe and meta.read_only


async def _execute_single(tool_name: str, arguments: dict[str, Any]) -> Any:
    """Execute a single registered tool by name."""
    registry = get_registered_tools()
    entry = registry.get(tool_name)
    if entry is None:
        raise ValueError(f"Tool not found: {tool_name}")
    fn = entry[0]
    result = fn(**arguments)
    if inspect.isawaitable(result):
        return await result
    return result


async def execute_tool_batch(tool_calls: list[ToolCall]) -> list[ToolResult]:
    """Execute a batch of tool calls with concurrency partitioning.

    Read-only + concurrent_safe tools run in parallel (up to MAX_TOOL_CONCURRENCY).
    All other tools run sequentially.
    Results returned in original request order.
    """
    if not tool_calls:
        return []

    read_batch: list[tuple[int, ToolCall]] = []
    write_batch: list[tuple[int, ToolCall]] = []

    for i, tc in enumerate(tool_calls):
        meta = get_tool_metadata(tc.name)
        if _is_concurrently_runnable(meta):
            read_batch.append((i, tc))
        else:
            write_batch.append((i, tc))

    results: dict[int, ToolResult] = {}
    sem = asyncio.Semaphore(MAX_TOOL_CONCURRENCY)

    async def _run_with_sem(index: int, tc: ToolCall) -> None:
        async with sem:
            try:
                result = await _execute_single(tc.name, tc.arguments)
                results[index] = ToolResult(name=tc.name, result=result)
            except Exception as exc:
                log.warning("Concurrent tool %s failed: %s", tc.name, exc)
                results[index] = ToolResult(name=tc.name, error="Tool execution failed")

    if read_batch:
        tasks = [_run_with_sem(i, tc) for i, tc in read_batch]
        await asyncio.gather(*tasks)

    for i, tc in write_batch:
        try:
            result = await _execute_single(tc.name, tc.arguments)
            results[i] = ToolResult(name=tc.name, result=result)
        except Exception as exc:
            log.warning("Sequential tool %s failed: %s", tc.name, exc)
            results[i] = ToolResult(name=tc.name, error="Tool execution failed")


    return [results[i] for i in sorted(results.keys())]
