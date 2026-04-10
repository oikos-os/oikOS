"""Tests for T-109 Gate 2: oikos_tool_search (tool #51)."""

import importlib

import pytest
from core.framework.decorator import (
    oikos_tool,
    ToolTier,
    get_registered_tools,
    clear_registry,
)


@pytest.fixture(autouse=True)
def clean_registry():
    clear_registry()
    yield
    clear_registry()


def _register_searchable_tools():
    """Register tools with diverse metadata for search testing."""
    @oikos_tool(name="vault_search", toolset="vault", tier=ToolTier.CORE,
                search_hint="find knowledge documents vault memory query",
                group="knowledge", concurrent_safe=True, read_only=True)
    def t1(q: str = "") -> dict:
        return {}

    @oikos_tool(name="file_read", toolset="file",
                search_hint="read file contents text view open",
                group="filesystem", concurrent_safe=True, read_only=True)
    def t2(path: str = "") -> dict:
        return {}

    @oikos_tool(name="file_delete", toolset="file",
                search_hint="delete remove file erase cleanup",
                group="filesystem", destructive=True)
    def t3(path: str = "") -> dict:
        return {}

    @oikos_tool(name="gmail_send", toolset="google",
                search_hint="gmail email send compose write message",
                group="google")
    def t4(to: str = "") -> dict:
        return {}

    @oikos_tool(name="web_search", toolset="browser",
                search_hint="search web internet query results searxng",
                group="web", concurrent_safe=True, read_only=True)
    def t5(q: str = "") -> dict:
        return {}


def _get_tool_search_fn():
    """Get the tool_search function from registry."""
    # Import the module to register it
    import core.framework.tools.tool_search
    importlib.reload(core.framework.tools.tool_search)
    registry = get_registered_tools()
    return registry["oikos_tool_search"][0]


class TestToolSearchSelect:
    def test_select_single_tool(self):
        _register_searchable_tools()
        search = _get_tool_search_fn()
        result = search(query="select:vault_search")
        assert result["mode"] == "select"
        assert result["count"] == 1
        assert result["matches"][0]["name"] == "vault_search"

    def test_select_multiple_tools(self):
        _register_searchable_tools()
        search = _get_tool_search_fn()
        result = search(query="select:vault_search,file_read")
        assert result["count"] == 2
        names = {m["name"] for m in result["matches"]}
        assert names == {"vault_search", "file_read"}

    def test_select_nonexistent(self):
        _register_searchable_tools()
        search = _get_tool_search_fn()
        result = search(query="select:nonexistent_tool")
        assert result["count"] == 0
        assert result["matches"] == []

    def test_select_mixed_exists_and_not(self):
        _register_searchable_tools()
        search = _get_tool_search_fn()
        result = search(query="select:vault_search,nonexistent")
        assert result["count"] == 1


class TestToolSearchKeyword:
    def test_search_by_description_keyword(self):
        _register_searchable_tools()
        search = _get_tool_search_fn()
        result = search(query="email send")
        assert result["mode"] == "search"
        assert result["count"] >= 1
        names = {m["name"] for m in result["matches"]}
        assert "gmail_send" in names

    def test_search_delete_files(self):
        _register_searchable_tools()
        search = _get_tool_search_fn()
        result = search(query="delete files")
        names = {m["name"] for m in result["matches"]}
        assert "file_delete" in names

    def test_search_nonsense_returns_empty(self):
        _register_searchable_tools()
        search = _get_tool_search_fn()
        result = search(query="xyzzy plugh")
        assert result["count"] == 0

    def test_search_empty_query(self):
        _register_searchable_tools()
        search = _get_tool_search_fn()
        result = search(query="")
        assert result["count"] == 0

    def test_search_max_results(self):
        _register_searchable_tools()
        search = _get_tool_search_fn()
        result = search(query="search", max_results=2)
        assert result["count"] <= 2

    def test_exact_name_scores_highest(self):
        _register_searchable_tools()
        search = _get_tool_search_fn()
        result = search(query="vault_search")
        assert result["matches"][0]["name"] == "vault_search"

    def test_toolset_match(self):
        _register_searchable_tools()
        search = _get_tool_search_fn()
        result = search(query="google")
        names = {m["name"] for m in result["matches"]}
        assert "gmail_send" in names


class TestToolSearchMeta:
    def _reload_all_tools(self):
        """Reload all tool modules to populate registry."""
        clear_registry()
        import core.framework.tools.vault_tools
        import core.framework.tools.system_tools
        import core.framework.tools.inference_tools
        import core.framework.tools.fs_tools
        import core.framework.tools.exec_tools
        import core.framework.tools.git_tools
        import core.framework.tools.oracle_tools
        import core.framework.tools.browser_tools
        import core.framework.tools.research_tools
        import core.framework.tools.google_tools
        import core.framework.tools.tool_search
        for mod in [
            core.framework.tools.vault_tools,
            core.framework.tools.system_tools,
            core.framework.tools.inference_tools,
            core.framework.tools.fs_tools,
            core.framework.tools.exec_tools,
            core.framework.tools.git_tools,
            core.framework.tools.oracle_tools,
            core.framework.tools.browser_tools,
            core.framework.tools.research_tools,
            core.framework.tools.google_tools,
            core.framework.tools.tool_search,
        ]:
            importlib.reload(mod)
        return get_registered_tools()

    def test_is_tool_51(self):
        """oikos_tool_search is registered and brings total to 51."""
        registry = self._reload_all_tools()
        assert "oikos_tool_search" in registry
        assert len(registry) == 51

    def test_is_core_tier(self):
        registry = self._reload_all_tools()
        meta = registry["oikos_tool_search"][1]
        assert meta.tier == ToolTier.CORE

    def test_is_concurrent_safe(self):
        registry = self._reload_all_tools()
        meta = registry["oikos_tool_search"][1]
        assert meta.concurrent_safe is True
        assert meta.read_only is True

    def test_result_includes_schema_fields(self):
        _register_searchable_tools()
        search = _get_tool_search_fn()
        result = search(query="select:vault_search")
        match = result["matches"][0]
        assert "name" in match
        assert "description" in match
        assert "toolset" in match
        assert "group" in match
        assert "concurrent_safe" in match
        assert "read_only" in match
        assert "destructive" in match
        assert "tier" in match
        assert "tags" in match


class TestToolSearchDispatch:
    """T-110 Gate 2 additional tests per dispatch requirements."""

    def test_select_vault_search(self):
        _register_searchable_tools()
        search = _get_tool_search_fn()
        result = search(query="select:vault_search")
        assert result["count"] == 1
        assert result["matches"][0]["name"] == "vault_search"

    def test_select_multiple_tools(self):
        _register_searchable_tools()
        search = _get_tool_search_fn()
        result = search(query="select:vault_search,file_read")
        assert result["count"] == 2
        names = {m["name"] for m in result["matches"]}
        assert names == {"vault_search", "file_read"}

    def test_keyword_email_send(self):
        _register_searchable_tools()
        search = _get_tool_search_fn()
        result = search(query="email send")
        names = [m["name"] for m in result["matches"]]
        assert "gmail_send" in names

    def test_keyword_delete_files(self):
        _register_searchable_tools()
        search = _get_tool_search_fn()
        result = search(query="delete file")
        names = [m["name"] for m in result["matches"]]
        assert "file_delete" in names

    def test_nonsense_query_empty(self):
        _register_searchable_tools()
        search = _get_tool_search_fn()
        result = search(query="zzzxyznonexistent")
        assert result["count"] == 0
        assert result["matches"] == []

    def test_max_results_cap(self):
        _register_searchable_tools()
        search = _get_tool_search_fn()
        result = search(query="file", max_results=2)
        assert len(result["matches"]) <= 2

    def test_exact_name_scores_higher_than_description(self):
        _register_searchable_tools()
        from core.framework.tools.tool_search import _score_tool
        from core.framework.decorator import get_registered_tools
        registry = get_registered_tools()
        vault_meta = registry["vault_search"][1]
        # Exact name match should score higher than a description-only match
        exact_score = _score_tool(vault_meta, ["vault_search"])
        desc_score = _score_tool(vault_meta, ["documents"])
        assert exact_score > desc_score
