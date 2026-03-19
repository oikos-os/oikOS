"""Tests for browser MCP tool registration."""

import pytest
from core.framework.decorator import get_registered_tools


class TestBrowserToolRegistration:
    def test_all_browser_tools_registered(self):
        import core.framework.tools.browser_tools  # noqa: F401
        tools = get_registered_tools()
        expected = [
            "oikos_web_fetch", "oikos_web_search", "oikos_web_extract",
            "oikos_web_screenshot", "oikos_web_navigate", "oikos_web_monitor",
        ]
        for name in expected:
            assert name in tools, f"Missing tool: {name}"

    def test_browser_tools_correct_toolset(self):
        import core.framework.tools.browser_tools  # noqa: F401
        tools = get_registered_tools()
        for name in ["oikos_web_fetch", "oikos_web_search", "oikos_web_extract",
                      "oikos_web_screenshot", "oikos_web_navigate", "oikos_web_monitor"]:
            _, meta = tools[name]
            assert meta.toolset == "browser", f"{name} should be in 'browser' toolset"

    def test_ask_first_tools(self):
        from core.interface.models import ActionClass
        import core.framework.tools.browser_tools  # noqa: F401
        tools = get_registered_tools()
        for name in ["oikos_web_navigate", "oikos_web_monitor"]:
            _, meta = tools[name]
            assert meta.autonomy == ActionClass.ASK_FIRST, f"{name} should be ASK_FIRST"

    def test_safe_tools(self):
        from core.interface.models import ActionClass
        import core.framework.tools.browser_tools  # noqa: F401
        tools = get_registered_tools()
        for name in ["oikos_web_fetch", "oikos_web_search", "oikos_web_extract", "oikos_web_screenshot"]:
            _, meta = tools[name]
            assert meta.autonomy == ActionClass.SAFE, f"{name} should be SAFE"

    def test_all_sensitive_privacy(self):
        from core.interface.models import DataTier
        import core.framework.tools.browser_tools  # noqa: F401
        tools = get_registered_tools()
        for name in ["oikos_web_fetch", "oikos_web_search", "oikos_web_extract",
                      "oikos_web_screenshot", "oikos_web_navigate", "oikos_web_monitor"]:
            _, meta = tools[name]
            assert meta.privacy == DataTier.SENSITIVE, f"{name} should be SENSITIVE"
