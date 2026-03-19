"""Autonomy middleware — enforces SAFE/ASK_FIRST/PROHIBITED via AutonomyMatrix."""

from __future__ import annotations

import logging
from typing import Any, Callable

from core.framework.exceptions import ApprovalRequired
from core.framework.middleware.base import MiddlewareContext
from core.interface.models import ActionClass

log = logging.getLogger(__name__)


class AutonomyMiddleware:
    """Checks autonomy classification before tool execution.

    SAFE: pass through. ASK_FIRST: create proposal, raise ApprovalRequired.
    PROHIBITED: raise PermissionError. Stricter of decorator vs matrix wins.
    """

    def __init__(self, matrix=None, queue=None):
        self._matrix = matrix
        self._queue = queue

    async def __call__(self, ctx: MiddlewareContext, call_next: Callable) -> Any:
        # Decorator-declared level
        declared = ctx.tool_meta.autonomy

        # Matrix-classified level (if matrix available)
        matrix_level = declared
        if self._matrix:
            try:
                matrix_level = self._matrix.classify_tool(ctx.tool_name)
            except (KeyError, ValueError):
                pass  # Tool not in matrix — use declared level

        # Stricter classification wins
        level = max(declared, matrix_level, key=_severity)

        # Room-level autonomy override (stricter wins)
        try:
            from core.rooms.manager import get_room_manager
            room = get_room_manager().get_active_room()
            room_override = room.autonomy.overrides.get(ctx.tool_name)
            if room_override:
                room_level = ActionClass(room_override)
                level = max(level, room_level, key=_severity)
        except Exception:
            pass  # Room system not initialized

        if level == ActionClass.PROHIBITED:
            raise PermissionError(f"Tool '{ctx.tool_name}' is PROHIBITED")

        if level == ActionClass.ASK_FIRST:
            if self._queue is None:
                raise PermissionError(f"Tool '{ctx.tool_name}' requires approval but no queue configured")
            proposal = self._queue.propose(
                action_type=ctx.tool_meta.toolset,
                tool_name=ctx.tool_name,
                tool_args=ctx.arguments,
                reason=f"ASK_FIRST tool invoked via MCP",
            )
            raise ApprovalRequired(proposal.proposal_id, ctx.tool_name)

        return await call_next()


def _severity(level: ActionClass) -> int:
    """Map ActionClass to severity for max() comparison."""
    return {ActionClass.SAFE: 0, ActionClass.ASK_FIRST: 1, ActionClass.PROHIBITED: 2}.get(level, 0)
