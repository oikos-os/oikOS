"""Tests for T-109 Gate 1: tool annotations (concurrent_safe, read_only, destructive, search_hint, group, tags)."""

import pytest
from core.framework.decorator import (
    oikos_tool,
    OikosToolMeta,
    ToolTier,
    get_registered_tools,
    clear_registry,
)


@pytest.fixture(autouse=True)
def clean_registry():
    clear_registry()
    yield
    clear_registry()


class TestAnnotationFields:
    def test_defaults_are_conservative(self):
        @oikos_tool(name="t1")
        def t() -> str:
            return "x"

        meta = t._oikos_meta
        assert meta.concurrent_safe is False
        assert meta.read_only is False
        assert meta.destructive is False
        assert meta.search_hint == ""
        assert meta.group == ""
        assert meta.tags == ()
        assert meta.tier == ToolTier.ROOM

    def test_concurrent_safe_read_only(self):
        @oikos_tool(name="t2", concurrent_safe=True, read_only=True)
        def t() -> str:
            return "x"

        meta = t._oikos_meta
        assert meta.concurrent_safe is True
        assert meta.read_only is True

    def test_destructive_flag(self):
        @oikos_tool(name="t3", destructive=True)
        def t() -> str:
            return "x"

        assert t._oikos_meta.destructive is True

    def test_search_hint(self):
        @oikos_tool(name="t4", search_hint="find search query lookup")
        def t() -> str:
            return "x"

        assert "search" in t._oikos_meta.search_hint

    def test_group(self):
        @oikos_tool(name="t5", group="knowledge")
        def t() -> str:
            return "x"

        assert t._oikos_meta.group == "knowledge"

    def test_tags_list_to_tuple(self):
        @oikos_tool(name="t6", tags=["stable", "fast"])
        def t() -> str:
            return "x"

        assert t._oikos_meta.tags == ("stable", "fast")
        assert isinstance(t._oikos_meta.tags, tuple)

    def test_tags_none_becomes_empty_tuple(self):
        @oikos_tool(name="t7", tags=None)
        def t() -> str:
            return "x"

        assert t._oikos_meta.tags == ()

    def test_tier_core(self):
        @oikos_tool(name="t8", tier=ToolTier.CORE)
        def t() -> str:
            return "x"

        assert t._oikos_meta.tier == ToolTier.CORE

    def test_tier_deferred(self):
        @oikos_tool(name="t9", tier=ToolTier.DEFERRED)
        def t() -> str:
            return "x"

        assert t._oikos_meta.tier == ToolTier.DEFERRED


class TestToolTierEnum:
    def test_values(self):
        assert ToolTier.CORE.value == "core"
        assert ToolTier.ROOM.value == "room"
        assert ToolTier.DEFERRED.value == "deferred"

    def test_is_string_enum(self):
        assert isinstance(ToolTier.CORE, str)
        assert ToolTier.CORE == "core"


class TestExistingToolAnnotations:
    """Verify all registered production tools have annotations."""

    def _load_production_tools(self):
        clear_registry()
        import importlib
        import core.framework.tools
        importlib.reload(core.framework.tools)
        return get_registered_tools()

    def test_all_tools_have_search_hint(self):
        tools = self._load_production_tools()
        missing = [name for name, (fn, meta) in tools.items() if not meta.search_hint]
        assert missing == [], f"Tools missing search_hint: {missing}"

    def test_all_tools_have_group(self):
        tools = self._load_production_tools()
        missing = [name for name, (fn, meta) in tools.items() if not meta.group]
        assert missing == [], f"Tools missing group: {missing}"

    def test_read_only_tools_are_concurrent_safe(self):
        """If a tool is marked read_only=True and concurrent_safe=True, both flags set."""
        tools = self._load_production_tools()
        for name, (fn, meta) in tools.items():
            if meta.concurrent_safe:
                assert meta.read_only, f"{name} is concurrent_safe but not read_only"

    def test_destructive_tools_are_not_concurrent_safe(self):
        tools = self._load_production_tools()
        for name, (fn, meta) in tools.items():
            if meta.destructive:
                assert not meta.concurrent_safe, f"{name} is destructive AND concurrent_safe"

    def test_every_tool_has_concurrent_safe_field(self):
        tools = self._load_production_tools()
        for name, (fn, meta) in tools.items():
            assert isinstance(meta.concurrent_safe, bool), f"{name} concurrent_safe is not bool"

    def test_every_tool_has_read_only_field(self):
        tools = self._load_production_tools()
        for name, (fn, meta) in tools.items():
            assert isinstance(meta.read_only, bool), f"{name} read_only is not bool"

    def test_every_tool_has_destructive_field(self):
        tools = self._load_production_tools()
        for name, (fn, meta) in tools.items():
            assert isinstance(meta.destructive, bool), f"{name} destructive is not bool"

    def test_core_tier_in_every_pool(self):
        """CORE tier tools appear in full_schema regardless of allowed_toolsets."""
        from core.framework.tool_pool import assemble_tool_pool
        tools = self._load_production_tools()
        core_names = {n for n, (fn, m) in tools.items() if m.tier == ToolTier.CORE}
        pool = assemble_tool_pool(["vault"])
        full_names = {m.name for m in pool.full_schema_tools}
        assert core_names.issubset(full_names), f"CORE tools missing from pool: {core_names - full_names}"

    def test_default_annotations_are_conservative(self):
        @oikos_tool(name="conservative_test")
        def t() -> str:
            return ""
        meta = t._oikos_meta
        assert meta.concurrent_safe is False
        assert meta.read_only is False
        assert meta.destructive is False
        assert meta.tier == ToolTier.ROOM
