"""Tests for research MCP tool registration."""

import importlib
import pytest
from core.framework.decorator import get_registered_tools


@pytest.fixture(autouse=True)
def _reload_tools():
    """Re-register tools in case clear_registry was called by earlier tests."""
    import core.framework.tools.research_tools as mod
    importlib.reload(mod)


class TestResearchToolRegistration:
    def test_all_research_tools_registered(self):
        tools = get_registered_tools()
        expected = [
            "oikos_research_queue", "oikos_research_run", "oikos_research_review",
            "oikos_research_approve", "oikos_research_reject",
        ]
        for name in expected:
            assert name in tools, f"Missing tool: {name}"

    def test_research_tools_correct_toolset(self):
        tools = get_registered_tools()
        for name in ["oikos_research_queue", "oikos_research_run", "oikos_research_review",
                      "oikos_research_approve", "oikos_research_reject"]:
            _, meta = tools[name]
            assert meta.toolset == "research", f"{name} should be in 'research' toolset"

    def test_ask_first_tools(self):
        from core.interface.models import ActionClass
        tools = get_registered_tools()
        for name in ["oikos_research_run", "oikos_research_approve"]:
            _, meta = tools[name]
            assert meta.autonomy == ActionClass.ASK_FIRST, f"{name} should be ASK_FIRST"

    def test_approve_is_never_leave(self):
        from core.interface.models import DataTier
        tools = get_registered_tools()
        _, meta = tools["oikos_research_approve"]
        assert meta.privacy == DataTier.NEVER_LEAVE
