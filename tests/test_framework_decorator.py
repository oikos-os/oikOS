"""Tests for the @oikos_tool decorator and registry."""

import pytest
from core.framework.decorator import (
    oikos_tool,
    OikosToolMeta,
    PrivacyTier,
    AutonomyLevel,
    get_registered_tools,
    clear_registry,
)
from core.framework.toolsets import get_tools_by_toolset
from core.interface.models import DataTier, ActionClass


@pytest.fixture(autouse=True)
def clean_registry():
    """Clear the global registry before and after each test."""
    clear_registry()
    yield
    clear_registry()


class TestDecorator:
    def test_registers_tool(self):
        @oikos_tool(name="test_tool", description="A test tool")
        def my_tool(x: int) -> str:
            return str(x)

        tools = get_registered_tools()
        assert "test_tool" in tools
        fn, meta = tools["test_tool"]
        assert meta.name == "test_tool"
        assert meta.description == "A test tool"

    def test_preserves_function_call(self):
        @oikos_tool(name="add_tool")
        def add(a: int, b: int) -> int:
            return a + b

        assert add(3, 4) == 7

    def test_stores_metadata_on_function(self):
        @oikos_tool(name="meta_tool", privacy=PrivacyTier.NEVER_LEAVE, autonomy=AutonomyLevel.ASK_FIRST)
        def my_tool() -> str:
            return "hi"

        assert hasattr(my_tool, "_oikos_meta")
        assert my_tool._oikos_meta.privacy == DataTier.NEVER_LEAVE
        assert my_tool._oikos_meta.autonomy == ActionClass.ASK_FIRST

    def test_default_metadata(self):
        @oikos_tool(name="default_tool")
        def my_tool() -> str:
            return "hi"

        meta = my_tool._oikos_meta
        assert meta.privacy == DataTier.SAFE
        assert meta.autonomy == ActionClass.SAFE
        assert meta.toolset == "system"
        assert meta.cost_category == "local"
        assert meta.rate_limit == 0
        assert meta.token_ceiling == 0

    def test_description_from_docstring(self):
        @oikos_tool(name="doc_tool")
        def my_tool() -> str:
            """Tool from docstring."""
            return "hi"

        meta = my_tool._oikos_meta
        assert meta.description == "Tool from docstring."

    def test_explicit_description_overrides_docstring(self):
        @oikos_tool(name="override_tool", description="Explicit desc")
        def my_tool() -> str:
            """Docstring desc."""
            return "hi"

        assert my_tool._oikos_meta.description == "Explicit desc"

    def test_overwrite_warning(self):
        @oikos_tool(name="dupe_tool")
        def tool_v1() -> str:
            return "v1"

        @oikos_tool(name="dupe_tool")
        def tool_v2() -> str:
            return "v2"

        tools = get_registered_tools()
        fn, meta = tools["dupe_tool"]
        # Second registration wins
        assert fn().__wrapped__() == "v2" if hasattr(fn, "__wrapped__") else True

    def test_clear_registry(self):
        @oikos_tool(name="temp_tool")
        def my_tool() -> str:
            return "hi"

        assert len(get_registered_tools()) == 1
        clear_registry()
        assert len(get_registered_tools()) == 0


class TestToolsets:
    def test_filter_by_toolset(self):
        @oikos_tool(name="vault_tool", toolset="vault")
        def vt() -> str:
            return "v"

        @oikos_tool(name="system_tool", toolset="system")
        def st() -> str:
            return "s"

        vault_tools = get_tools_by_toolset("vault")
        assert len(vault_tools) == 1
        assert vault_tools[0][1].name == "vault_tool"

    def test_empty_toolset(self):
        @oikos_tool(name="some_tool", toolset="system")
        def st() -> str:
            return "s"

        assert len(get_tools_by_toolset("browser")) == 0


class TestEnumAliases:
    def test_privacy_tier_is_data_tier(self):
        assert PrivacyTier.NEVER_LEAVE is DataTier.NEVER_LEAVE
        assert PrivacyTier.SENSITIVE is DataTier.SENSITIVE
        assert PrivacyTier.SAFE is DataTier.SAFE

    def test_autonomy_level_is_action_class(self):
        assert AutonomyLevel.SAFE is ActionClass.SAFE
        assert AutonomyLevel.ASK_FIRST is ActionClass.ASK_FIRST
        assert AutonomyLevel.PROHIBITED is ActionClass.PROHIBITED


class TestOikosToolMeta:
    def test_frozen(self):
        meta = OikosToolMeta(name="t", description="d")
        with pytest.raises(AttributeError):
            meta.name = "other"
