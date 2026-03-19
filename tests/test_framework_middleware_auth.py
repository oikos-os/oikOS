"""Tests for auth middleware."""

import asyncio
import pytest
from unittest.mock import patch

from core.framework.middleware.auth import AuthMiddleware
from core.framework.middleware.base import MiddlewareContext
from core.framework.decorator import OikosToolMeta


def _make_ctx(**extras):
    return MiddlewareContext(
        tool_name="test",
        tool_meta=OikosToolMeta(name="test", description="test"),
        arguments={},
        extras=extras,
    )


async def _noop():
    return "ok"


class TestAuthMiddleware:
    def test_no_key_configured_passes(self):
        mw = AuthMiddleware()
        ctx = _make_ctx()
        with patch.dict("os.environ", {}, clear=True):
            result = asyncio.get_event_loop().run_until_complete(mw(ctx, _noop))
        assert result == "ok"

    def test_valid_key_passes(self):
        mw = AuthMiddleware()
        ctx = _make_ctx(api_key="secret123")
        with patch.dict("os.environ", {"OIKOS_API_KEY": "secret123"}):
            result = asyncio.get_event_loop().run_until_complete(mw(ctx, _noop))
        assert result == "ok"

    def test_invalid_key_raises(self):
        mw = AuthMiddleware()
        ctx = _make_ctx(api_key="wrong")
        with patch.dict("os.environ", {"OIKOS_API_KEY": "secret123"}):
            with pytest.raises(PermissionError, match="Invalid or missing"):
                asyncio.get_event_loop().run_until_complete(mw(ctx, _noop))

    def test_missing_key_raises(self):
        mw = AuthMiddleware()
        ctx = _make_ctx()  # no api_key in extras
        with patch.dict("os.environ", {"OIKOS_API_KEY": "secret123"}):
            with pytest.raises(PermissionError, match="Invalid or missing"):
                asyncio.get_event_loop().run_until_complete(mw(ctx, _noop))

    def test_empty_key_raises(self):
        mw = AuthMiddleware()
        ctx = _make_ctx(api_key="")
        with patch.dict("os.environ", {"OIKOS_API_KEY": "secret123"}):
            with pytest.raises(PermissionError):
                asyncio.get_event_loop().run_until_complete(mw(ctx, _noop))
