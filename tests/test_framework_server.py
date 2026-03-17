"""Tests for OikosServer."""

import asyncio
import pytest
from unittest.mock import MagicMock, patch

from core.framework.decorator import oikos_tool, clear_registry, PrivacyTier, AutonomyLevel
from core.framework.server import OikosServer


@pytest.fixture(autouse=True)
def clean():
    clear_registry()
    yield
    clear_registry()


def _register_test_tools():
    @oikos_tool(name="safe_tool", description="A safe tool", toolset="system")
    def safe_tool(x: int) -> int:
        return x * 2

    @oikos_tool(name="vault_tool", description="A vault tool", toolset="vault")
    def vault_tool(query: str) -> str:
        return f"found: {query}"

    return safe_tool, vault_tool


class TestToolRegistration:
    def test_registers_all_tools(self):
        _register_test_tools()
        server = OikosServer(name="test", middleware=[])
        count = server.register_tools()
        assert count == 2

    def test_filters_by_toolset(self):
        _register_test_tools()
        server = OikosServer(name="test", middleware=[])
        count = server.register_tools(toolset="vault")
        assert count == 1

    def test_filters_by_name(self):
        _register_test_tools()
        server = OikosServer(name="test", middleware=[])
        count = server.register_tools(tools=["safe_tool"])
        assert count == 1

    def test_empty_registry_registers_zero(self):
        server = OikosServer(name="test", middleware=[])
        count = server.register_tools()
        assert count == 0


class TestMiddlewareChain:
    def test_chain_executes_tool(self):
        @oikos_tool(name="double", description="doubles")
        def double(x: int) -> int:
            return x * 2

        server = OikosServer(name="test", middleware=[])
        server.register_tools()

        # Call the wrapper directly
        wrapper = server._build_wrapper(double, double._oikos_meta)
        result = asyncio.get_event_loop().run_until_complete(wrapper(x=5))
        assert result == 10

    def test_chain_runs_middleware_in_order(self):
        call_order = []

        class TrackingMiddleware:
            def __init__(self, name):
                self.name = name

            async def __call__(self, ctx, call_next):
                call_order.append(f"pre:{self.name}")
                result = await call_next()
                call_order.append(f"post:{self.name}")
                return result

        @oikos_tool(name="tracked", description="tracked")
        def tracked() -> str:
            call_order.append("execute")
            return "done"

        server = OikosServer(
            name="test",
            middleware=[TrackingMiddleware("A"), TrackingMiddleware("B")],
        )
        server.register_tools()
        wrapper = server._build_wrapper(tracked, tracked._oikos_meta)
        asyncio.get_event_loop().run_until_complete(wrapper())

        assert call_order == ["pre:A", "pre:B", "execute", "post:B", "post:A"]

    def test_async_tool_supported(self):
        @oikos_tool(name="async_tool", description="async")
        async def async_tool(x: int) -> int:
            return x + 1

        server = OikosServer(name="test", middleware=[])
        server.register_tools()
        wrapper = server._build_wrapper(async_tool, async_tool._oikos_meta)
        result = asyncio.get_event_loop().run_until_complete(wrapper(x=10))
        assert result == 11

    def test_default_middleware_includes_privacy(self):
        from core.framework.middleware.privacy import PrivacyMiddleware
        server = OikosServer(name="test")
        has_privacy = any(isinstance(m, PrivacyMiddleware) for m in server._middleware)
        assert has_privacy


class TestMCPProperty:
    def test_exposes_fastmcp(self):
        server = OikosServer(name="test", middleware=[])
        assert server.mcp is not None
        assert hasattr(server.mcp, "add_tool")
