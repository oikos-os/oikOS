"""Error handling middleware — masks raw exceptions before MCP transport."""

from __future__ import annotations

import logging
from typing import Any, Callable

from core.framework.exceptions import ApprovalRequired
from core.framework.middleware.base import MiddlewareContext

log = logging.getLogger(__name__)


class ErrorHandlerMiddleware:
    """Catches exceptions from tool execution and returns sanitized errors.

    Uses ToolError from MCP SDK which FastMCP handles natively
    (avoids schema validation conflicts with return type).
    """

    async def __call__(self, ctx: MiddlewareContext, call_next: Callable) -> Any:
        try:
            return await call_next()
        except ApprovalRequired as exc:
            log.info("ASK_FIRST: %s requires approval (proposal: %s)", exc.tool_name, exc.proposal_id)
            return {
                "status": "approval_required",
                "tool": exc.tool_name,
                "proposal_id": exc.proposal_id,
                "message": f"This action requires Architect approval. Tool: {exc.tool_name}, args: {_summarize_args(ctx.arguments)}. Approve via the approval queue (proposal: {exc.proposal_id}).",
            }
        except PermissionError as exc:
            log.warning("Permission denied on tool %s: %s", ctx.tool_name, exc)
            _raise_tool_error("Permission denied")
        except (FileNotFoundError, IsADirectoryError):
            _raise_tool_error("File or path not found")
        except ValueError as exc:
            _raise_tool_error(f"Invalid input: {_safe_msg(exc)}")
        except Exception as exc:
            log.error("Tool %s failed: %s: %s", ctx.tool_name, type(exc).__name__, exc)
            _raise_tool_error(f"Tool error: {type(exc).__name__}")


def _raise_tool_error(message: str) -> None:
    """Raise MCP ToolError with sanitized message."""
    try:
        from mcp.server.fastmcp.exceptions import ToolError
        raise ToolError(message)
    except ImportError:
        raise RuntimeError(message)


def _safe_msg(exc: Exception) -> str:
    """Extract a safe error message — strip file paths and URLs."""
    msg = str(exc)
    if len(msg) > 200:
        msg = msg[:200] + "..."
    return msg


def _summarize_args(args: dict) -> str:
    """Summarize tool arguments for the approval prompt (no raw content)."""
    parts = []
    for k, v in args.items():
        if k == "content":
            parts.append(f"content=({len(v) if isinstance(v, (str, bytes)) else type(v).__name__})")
        else:
            parts.append(f"{k}={v!r}")
    return ", ".join(parts) if parts else "(none)"
