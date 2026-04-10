"""Tests for the Vault view (TUI-3)."""
from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
from textual.app import App, ComposeResult
from textual.widgets import DirectoryTree, Input, Markdown, Static

from core.interface.tui.client import OikOSClient
from core.interface.tui.views.vault import VaultView, _resolve_vault_path


# ---------------------------------------------------------------------------
# Test harness — minimal App wrapping VaultView
# ---------------------------------------------------------------------------

class VaultTestApp(App):
    def compose(self) -> ComposeResult:
        yield VaultView(id="vault")


# ---------------------------------------------------------------------------
# Widget composition tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_vault_view_composes():
    """VaultView mounts without error."""
    app = VaultTestApp()
    async with app.run_test(size=(120, 40)):
        vault = app.query_one(VaultView)
        assert vault is not None


@pytest.mark.asyncio
async def test_vault_has_search_input():
    """Vault contains the search bar."""
    app = VaultTestApp()
    async with app.run_test(size=(120, 40)):
        search = app.query_one("#vault-search", Input)
        assert search is not None
        assert search.placeholder == "Search vault..."


@pytest.mark.asyncio
async def test_vault_has_directory_tree_or_placeholder():
    """Vault contains a DirectoryTree if vault/ exists, else a Static placeholder."""
    app = VaultTestApp()
    async with app.run_test(size=(120, 40)):
        tree_widget = app.query_one("#vault-tree")
        assert tree_widget is not None


@pytest.mark.asyncio
async def test_vault_has_preview_pane():
    """Vault contains the markdown preview widget."""
    app = VaultTestApp()
    async with app.run_test(size=(120, 40)):
        preview = app.query_one("#file-preview", Markdown)
        assert preview is not None


@pytest.mark.asyncio
async def test_vault_has_file_bindings():
    """Vault has N/E/D/I keybindings for file operations."""
    app = VaultTestApp()
    async with app.run_test(size=(120, 40)):
        vault = app.query_one(VaultView)
        keys = [b.key for b in vault.BINDINGS]
        assert "n" in keys
        assert "e" in keys
        assert "d" in keys
        assert "i" in keys


@pytest.mark.asyncio
async def test_vault_has_metadata_bar():
    """Vault contains the file metadata display."""
    app = VaultTestApp()
    async with app.run_test(size=(120, 40)):
        meta = app.query_one("#file-meta", Static)
        assert meta is not None


@pytest.mark.asyncio
async def test_vault_header_update():
    """update_header sets the file count in the header."""
    app = VaultTestApp()
    async with app.run_test(size=(120, 40)) as pilot:
        vault = app.query_one(VaultView)
        vault.update_header(42)
        await pilot.pause()
        text = str(app.query_one("#vault-header", Static).render())
        assert "42" in text


@pytest.mark.asyncio
async def test_vault_preview_on_file_select():
    """Selecting a file in the tree populates the preview pane."""
    with tempfile.TemporaryDirectory() as tmpdir:
        test_file = Path(tmpdir) / "test.md"
        test_file.write_text("# Test Heading\nSome content here.", encoding="utf-8")

        app = VaultTestApp()
        async with app.run_test(size=(120, 40)) as pilot:
            vault = app.query_one(VaultView)
            # Set vault path to temp dir so containment check passes
            vault._vault_path = Path(tmpdir)
            vault._load_preview(test_file)
            await pilot.pause()
            meta_text = str(app.query_one("#file-meta", Static).render())
            assert "test.md" in meta_text


@pytest.mark.asyncio
async def test_vault_tier_extraction():
    """Tier is extracted from YAML frontmatter."""
    app = VaultTestApp()
    async with app.run_test(size=(120, 40)):
        vault = app.query_one(VaultView)
        content_with_tier = "---\ntier: SEMANTIC\ntags: [ml]\n---\n# Content"
        assert vault._extract_tier(content_with_tier) == "SEMANTIC"
        assert vault._extract_tier("# No frontmatter") == ""


# ---------------------------------------------------------------------------
# Client search method
# ---------------------------------------------------------------------------

def _make_search_transport():
    """Mock transport that responds to /api/search."""
    def handler(request: httpx.Request) -> httpx.Response:
        if "/api/search" in str(request.url):
            return httpx.Response(200, json={
                "query": "test",
                "results": [
                    {"content": "result 1", "source_path": "vault/test.md", "score": 0.9, "tier": "SEMANTIC"},
                    {"content": "result 2", "source_path": "vault/other.md", "score": 0.7, "tier": None},
                ],
                "count": 2,
            })
        return httpx.Response(404, json={"detail": "not found"})
    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_client_search_returns_results():
    """OikOSClient.search returns the results list."""
    transport = _make_search_transport()
    client = OikOSClient(transport=transport)
    results = await client.search("test", limit=5)
    assert len(results) == 2
    assert results[0]["source_path"] == "vault/test.md"
    assert results[0]["score"] == 0.9
    await client.close()


@pytest.mark.asyncio
async def test_client_search_fallback_on_error():
    """OikOSClient.search returns empty list on failure."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"detail": "error"})
    transport = httpx.MockTransport(handler)
    client = OikOSClient(transport=transport)
    results = await client.search("fail")
    assert results == []
    await client.close()
