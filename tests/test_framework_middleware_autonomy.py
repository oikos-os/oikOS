"""Tests for autonomy middleware."""

import asyncio
import pytest
from unittest.mock import MagicMock

from core.framework.middleware.autonomy import AutonomyMiddleware
from core.framework.middleware.base import MiddlewareContext
from core.framework.decorator import OikosToolMeta
from core.framework.exceptions import ApprovalRequired
from core.interface.models import ActionClass


def _make_ctx(autonomy=ActionClass.SAFE):
    return MiddlewareContext(
        tool_name="test_tool",
        tool_meta=OikosToolMeta(name="test_tool", description="test", autonomy=autonomy),
        arguments={"x": 1},
    )


async def _noop():
    return "executed"


class TestAutonomyMiddleware:
    def test_safe_passes(self):
        mw = AutonomyMiddleware()
        ctx = _make_ctx(ActionClass.SAFE)
        result = asyncio.get_event_loop().run_until_complete(mw(ctx, _noop))
        assert result == "executed"

    def test_prohibited_raises(self):
        mw = AutonomyMiddleware()
        ctx = _make_ctx(ActionClass.PROHIBITED)
        with pytest.raises(PermissionError, match="PROHIBITED"):
            asyncio.get_event_loop().run_until_complete(mw(ctx, _noop))

    def test_ask_first_creates_proposal(self):
        queue = MagicMock()
        proposal = MagicMock()
        proposal.proposal_id = "prop-123"
        queue.propose.return_value = proposal

        mw = AutonomyMiddleware(queue=queue)
        ctx = _make_ctx(ActionClass.ASK_FIRST)
        with pytest.raises(ApprovalRequired) as exc_info:
            asyncio.get_event_loop().run_until_complete(mw(ctx, _noop))
        assert exc_info.value.proposal_id == "prop-123"
        queue.propose.assert_called_once()

    def test_ask_first_no_queue_raises_permission(self):
        mw = AutonomyMiddleware(queue=None)
        ctx = _make_ctx(ActionClass.ASK_FIRST)
        with pytest.raises(PermissionError, match="requires approval"):
            asyncio.get_event_loop().run_until_complete(mw(ctx, _noop))

    def test_matrix_overrides_decorator_stricter(self):
        matrix = MagicMock()
        matrix.classify_tool.return_value = ActionClass.PROHIBITED

        mw = AutonomyMiddleware(matrix=matrix)
        ctx = _make_ctx(ActionClass.SAFE)  # decorator says SAFE
        with pytest.raises(PermissionError, match="PROHIBITED"):
            asyncio.get_event_loop().run_until_complete(mw(ctx, _noop))

    def test_decorator_overrides_matrix_stricter(self):
        matrix = MagicMock()
        matrix.classify_tool.return_value = ActionClass.SAFE

        mw = AutonomyMiddleware(matrix=matrix)
        ctx = _make_ctx(ActionClass.PROHIBITED)  # decorator is stricter
        with pytest.raises(PermissionError, match="PROHIBITED"):
            asyncio.get_event_loop().run_until_complete(mw(ctx, _noop))

    def test_matrix_not_found_uses_decorator(self):
        matrix = MagicMock()
        matrix.classify_tool.side_effect = KeyError("unknown tool")

        mw = AutonomyMiddleware(matrix=matrix)
        ctx = _make_ctx(ActionClass.SAFE)
        result = asyncio.get_event_loop().run_until_complete(mw(ctx, _noop))
        assert result == "executed"

    def test_safe_does_not_call_queue(self):
        queue = MagicMock()
        mw = AutonomyMiddleware(queue=queue)
        ctx = _make_ctx(ActionClass.SAFE)
        asyncio.get_event_loop().run_until_complete(mw(ctx, _noop))
        queue.propose.assert_not_called()
