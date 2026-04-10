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
                "message": f"Action requires approval. Tool: {exc.tool_name}, args: {_summarize_args(ctx.arguments)}. Approve via TUI (F9), CLI (oikos approvals), or API. Proposal: {exc.proposal_id}.",
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


import re as _re

_URL_RE = _re.compile(r"https?://\S+")
_PATH_RE = _re.compile(r"[A-Za-z]:\\[\w\\./\- ]+|/[\w/.\- ]{3,}")


def _safe_msg(exc: Exception) -> str:
    """Extract a safe error message — strip file paths and URLs."""
    msg = str(exc)
    msg = _URL_RE.sub("[url]", msg)
    msg = _PATH_RE.sub("[path]", msg)
    if len(msg) > 200:
        msg = msg[:200] + "..."
    return msg


def _summarize_args(args: dict) -> str:
    """Summarize tool arguments for the approval prompt (no raw content or paths)."""
    parts = []
    for k, v in args.items():
        if k == "content":
            parts.append(f"content=({len(v) if isinstance(v, (str, bytes)) else type(v).__name__})")
        elif k in ("path", "cwd", "source", "destination"):
            parts.append(f"{k}=[redacted]")
        else:
            s = repr(v)
            s = _PATH_RE.sub("[path]", s)
            s = _URL_RE.sub("[url]", s)
            if len(s) > 80:
                s = s[:77] + "..."
            parts.append(f"{k}={s}")
    return ", ".join(parts) if parts else "(none)"
