"""Tests for T-109 Gate 2: tool pool assembly and deferred loading."""

import pytest
from core.framework.decorator import (
    oikos_tool,
    OikosToolMeta,
    ToolTier,
    get_registered_tools,
    clear_registry,
)
from core.framework.tool_pool import assemble_tool_pool, render_deferred_listing, ToolPool


@pytest.fixture(autouse=True)
def clean_registry():
    clear_registry()
    yield
    clear_registry()


def _register_test_tools():
    """Register tools across tiers and toolsets."""
    @oikos_tool(name="core_search", tier=ToolTier.CORE, toolset="vault",
                search_hint="search", group="knowledge", concurrent_safe=True, read_only=True)
    def t1(q: str = "") -> dict:
        return {}

    @oikos_tool(name="core_status", tier=ToolTier.CORE, toolset="system",
                search_hint="status", group="system", concurrent_safe=True, read_only=True)
    def t2() -> dict:
        return {}

    @oikos_tool(name="vault_index", tier=ToolTier.ROOM, toolset="vault",
                search_hint="index", group="knowledge")
    def t3() -> dict:
        return {}

    @oikos_tool(name="file_read", tier=ToolTier.ROOM, toolset="file",
                search_hint="read file", group="filesystem", concurrent_safe=True, read_only=True)
    def t4(path: str = "") -> dict:
        return {}

    @oikos_tool(name="file_write", tier=ToolTier.ROOM, toolset="file",
                search_hint="write file", group="filesystem")
    def t5(path: str = "", content: str = "") -> dict:
        return {}

    @oikos_tool(name="browser_fetch", tier=ToolTier.ROOM, toolset="browser",
                search_hint="fetch web", group="web", concurrent_safe=True, read_only=True)
    def t6(url: str = "") -> dict:
        return {}


class TestToolPoolAssembly:
    def test_all_toolsets_returns_all_full_schema(self):
        _register_test_tools()
        pool = assemble_tool_pool(allowed_toolsets=None)
        assert pool.total_count == 6
        assert len(pool.full_schema_tools) == 6
        assert len(pool.deferred_tools) == 0

    def test_core_tools_always_in_full_schema(self):
        _register_test_tools()
        pool = assemble_tool_pool(allowed_toolsets=["file"])
        core_names = {m.name for m in pool.full_schema_tools if m.tier == ToolTier.CORE}
        assert "core_search" in core_names
        assert "core_status" in core_names

    def test_room_tools_filtered_by_toolset(self):
        _register_test_tools()
        pool = assemble_tool_pool(allowed_toolsets=["vault"])
        full_names = {m.name for m in pool.full_schema_tools}
        deferred_names = {m.name for m in pool.deferred_tools}
        # CORE tools + vault tools in full
        assert "core_search" in full_names
        assert "core_status" in full_names
        assert "vault_index" in full_names
        # file + browser tools deferred
        assert "file_read" in deferred_names
        assert "file_write" in deferred_names
        assert "browser_fetch" in deferred_names

    def test_multiple_toolsets(self):
        _register_test_tools()
        pool = assemble_tool_pool(allowed_toolsets=["vault", "file"])
        full_names = {m.name for m in pool.full_schema_tools}
        deferred_names = {m.name for m in pool.deferred_tools}
        assert "vault_index" in full_names
        assert "file_read" in full_names
        assert "file_write" in full_names
        assert "browser_fetch" in deferred_names

    def test_empty_toolsets_only_core(self):
        _register_test_tools()
        pool = assemble_tool_pool(allowed_toolsets=[])
        assert len(pool.full_schema_tools) == 2  # only CORE tools
        assert all(m.tier == ToolTier.CORE for m in pool.full_schema_tools)

    def test_total_count_correct(self):
        _register_test_tools()
        pool = assemble_tool_pool(allowed_toolsets=["vault"])
        assert pool.total_count == len(pool.full_schema_tools) + len(pool.deferred_tools)
        assert pool.total_count == 6


class TestDeferredListing:
    def test_empty_list(self):
        assert render_deferred_listing([]) == ""

    def test_renders_tools(self):
        _register_test_tools()
        pool = assemble_tool_pool(allowed_toolsets=["vault"])
        listing = render_deferred_listing(pool.deferred_tools)
        assert "oikos_tool_search" in listing or "file_read" in listing
        assert "Additional Tools Available" in listing

    def test_sorted_by_name(self):
        _register_test_tools()
        pool = assemble_tool_pool(allowed_toolsets=[])
        listing = render_deferred_listing(pool.deferred_tools)
        lines = [l for l in listing.split("\n") if l.startswith("- ")]
        names = [l.split(":")[0].lstrip("- ") for l in lines]
        assert names == sorted(names)

    def test_includes_group_tag(self):
        _register_test_tools()
        pool = assemble_tool_pool(allowed_toolsets=[])
        listing = render_deferred_listing(pool.deferred_tools)
        assert "[filesystem]" in listing or "[web]" in listing or "[knowledge]" in listing
