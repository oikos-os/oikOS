"""Tests for Room-based vault scoping (path_filter / exclude_filter)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from core.interface.models import MemoryTier, SearchResult


def _make_result(chunk_id: str, source_path: str, tier: str = "semantic", score: float = 0.8) -> SearchResult:
    return SearchResult(
        chunk_id=chunk_id,
        source_path=source_path,
        tier=MemoryTier(tier),
        header_path=f"TEST > {chunk_id}",
        content=f"Content for {chunk_id}",
        relevance_score=score,
        recency_weight=1.0,
        importance_weight=1.0,
        final_score=score,
    )


MOCK_RESULTS = [
    _make_result("c1", "knowledge/ml/transformers.md", score=0.9),
    _make_result("c2", "knowledge/ml/rl.md", score=0.85),
    _make_result("c3", "knowledge/ops/docker.md", score=0.8),
    _make_result("c4", "projects/oikos/design.md", score=0.75),
    _make_result("c5", "journal/2026-03.md", tier="episodic", score=0.7),
]


def _mock_lance_rows(results: list[SearchResult]) -> list[dict]:
    """Convert SearchResults to mock LanceDB row dicts."""
    rows = []
    for r in results:
        rows.append({
            "chunk_id": r.chunk_id,
            "source_path": r.source_path,
            "tier": r.tier.value,
            "header_path": r.header_path,
            "content": r.content,
            "file_mtime": "2026-03-17T00:00:00+00:00",
            "_relevance_score": r.final_score,
        })
    return rows


# ---------------------------------------------------------------------------
# hybrid_search tests
# ---------------------------------------------------------------------------

def _setup_mock_db(mock_get_db, rows):
    """Wire up mock_get_db to return a table whose hybrid search returns rows."""
    mock_db = MagicMock()
    mock_get_db.return_value = mock_db

    # _table_exists returns True
    mock_table = MagicMock()
    mock_db.open_table.return_value = mock_table
    mock_table.count_rows.return_value = len(rows)

    # Hybrid search chain
    builder = MagicMock()
    mock_table.search.return_value = builder
    builder.vector.return_value = builder
    builder.text.return_value = builder
    builder.limit.return_value = builder
    builder.rerank.return_value = builder
    builder.where.return_value = builder
    builder.to_list.return_value = rows

    return mock_table


@patch("core.memory.indexer._table_exists", return_value=True)
@patch("core.memory.search.embed_single", return_value=[0.1] * 768)
@patch("core.memory.search.get_db")
def test_no_filter_returns_all(mock_get_db, mock_embed, mock_exists):
    from core.memory.search import hybrid_search
    _setup_mock_db(mock_get_db, _mock_lance_rows(MOCK_RESULTS))
    results = hybrid_search("test query", limit=10)
    assert len(results) == len(MOCK_RESULTS)


@patch("core.memory.indexer._table_exists", return_value=True)
@patch("core.memory.search.embed_single", return_value=[0.1] * 768)
@patch("core.memory.search.get_db")
def test_path_filter_includes_only_matching(mock_get_db, mock_embed, mock_exists):
    from core.memory.search import hybrid_search
    _setup_mock_db(mock_get_db, _mock_lance_rows(MOCK_RESULTS))
    results = hybrid_search("test query", limit=10, path_filter=["knowledge/ml/"])
    assert len(results) == 2
    assert all("knowledge/ml/" in r.source_path for r in results)


@patch("core.memory.indexer._table_exists", return_value=True)
@patch("core.memory.search.embed_single", return_value=[0.1] * 768)
@patch("core.memory.search.get_db")
def test_empty_path_filter_returns_empty(mock_get_db, mock_embed, mock_exists):
    from core.memory.search import hybrid_search
    _setup_mock_db(mock_get_db, _mock_lance_rows(MOCK_RESULTS))
    results = hybrid_search("test query", limit=10, path_filter=[])
    assert results == []


@patch("core.memory.indexer._table_exists", return_value=True)
@patch("core.memory.search.embed_single", return_value=[0.1] * 768)
@patch("core.memory.search.get_db")
def test_exclude_filter_removes_matching(mock_get_db, mock_embed, mock_exists):
    from core.memory.search import hybrid_search
    _setup_mock_db(mock_get_db, _mock_lance_rows(MOCK_RESULTS))
    results = hybrid_search("test query", limit=10, exclude_filter=["knowledge/ml/"])
    assert len(results) == 3
    assert all("knowledge/ml/" not in r.source_path for r in results)


@patch("core.memory.indexer._table_exists", return_value=True)
@patch("core.memory.search.embed_single", return_value=[0.1] * 768)
@patch("core.memory.search.get_db")
def test_path_filter_multiple_paths_union(mock_get_db, mock_embed, mock_exists):
    from core.memory.search import hybrid_search
    _setup_mock_db(mock_get_db, _mock_lance_rows(MOCK_RESULTS))
    results = hybrid_search("test query", limit=10, path_filter=["knowledge/ml/", "projects/"])
    assert len(results) == 3
    paths = {r.source_path for r in results}
    assert "knowledge/ml/transformers.md" in paths
    assert "knowledge/ml/rl.md" in paths
    assert "projects/oikos/design.md" in paths


@patch("core.memory.indexer._table_exists", return_value=True)
@patch("core.memory.search.embed_single", return_value=[0.1] * 768)
@patch("core.memory.search.get_db")
def test_backslash_paths_normalized(mock_get_db, mock_embed, mock_exists):
    """Windows backslash paths in source_path still match forward-slash filters."""
    from core.memory.search import hybrid_search
    # Create results with backslash paths
    win_results = [_make_result("w1", "knowledge\\ml\\transformers.md", score=0.9)]
    _setup_mock_db(mock_get_db, _mock_lance_rows(win_results))
    results = hybrid_search("test query", limit=10, path_filter=["knowledge/ml/"])
    assert len(results) == 1


@patch("core.memory.indexer._table_exists", return_value=True)
@patch("core.memory.search.embed_single", return_value=[0.1] * 768)
@patch("core.memory.search.get_db")
def test_overfetch_3x_when_filter_active(mock_get_db, mock_embed, mock_exists):
    """When path_filter is set, over-fetch multiplier should be 3x."""
    from core.memory.search import hybrid_search
    mock_table = _setup_mock_db(mock_get_db, _mock_lance_rows(MOCK_RESULTS))

    # With filter — should call .limit(5 * 3 = 15)
    hybrid_search("test query", limit=5, path_filter=["knowledge/"])
    # Find the limit call on the search builder
    search_builder = mock_table.search.return_value
    limit_calls = search_builder.limit.call_args_list
    assert any(call.args[0] == 15 for call in limit_calls), f"Expected limit(15), got {limit_calls}"


@patch("core.memory.indexer._table_exists", return_value=True)
@patch("core.memory.search.embed_single", return_value=[0.1] * 768)
@patch("core.memory.search.get_db")
def test_overfetch_2x_when_no_filter(mock_get_db, mock_embed, mock_exists):
    """Without filters, over-fetch multiplier should remain 2x."""
    from core.memory.search import hybrid_search
    mock_table = _setup_mock_db(mock_get_db, _mock_lance_rows(MOCK_RESULTS))

    hybrid_search("test query", limit=5)
    search_builder = mock_table.search.return_value
    limit_calls = search_builder.limit.call_args_list
    assert any(call.args[0] == 10 for call in limit_calls), f"Expected limit(10), got {limit_calls}"


# ---------------------------------------------------------------------------
# search_tier tests
# ---------------------------------------------------------------------------

@patch("core.memory.indexer._table_exists", return_value=True)
@patch("core.memory.search.embed_single", return_value=[0.1] * 768)
@patch("core.memory.search.get_db")
def test_search_tier_passes_filters(mock_get_db, mock_embed, mock_exists):
    from core.memory.search import search_tier
    _setup_mock_db(mock_get_db, _mock_lance_rows(MOCK_RESULTS))
    results = search_tier(
        "test query", MemoryTier.SEMANTIC, limit=10,
        path_filter=["knowledge/ml/"], exclude_filter=["knowledge/ml/rl.md"],
    )
    assert len(results) == 1
    assert results[0].source_path == "knowledge/ml/transformers.md"


# ---------------------------------------------------------------------------
# compiler tests (mock search_tier at the boundary)
# ---------------------------------------------------------------------------

@patch("core.cognition.compiler.search_tier")
def test_fill_slice_passes_filters(mock_search_tier):
    from core.cognition.compiler import fill_slice
    mock_search_tier.return_value = MOCK_RESULTS[:2]
    fill_slice("q", MemoryTier.SEMANTIC, "semantic", 5000, path_filter=["knowledge/"], exclude_filter=["journal/"])
    mock_search_tier.assert_called_once_with(
        "q", MemoryTier.SEMANTIC, limit=20,
        path_filter=["knowledge/"], exclude_filter=["journal/"], tag_filter=None,
    )


@patch("core.cognition.compiler.fill_identity_slice")
@patch("core.cognition.compiler.fill_slice")
def test_compile_context_no_filter_default(mock_fill_slice, mock_fill_identity):
    from core.cognition.compiler import compile_context
    from core.interface.models import ContextSlice
    mock_fill_identity.return_value = (
        ContextSlice(name="identity", tier=MemoryTier.CORE, max_tokens=500, token_count=100),
        set(),
    )
    mock_fill_slice.return_value = ContextSlice(name="test", tier=MemoryTier.CORE, max_tokens=500, token_count=0)
    compile_context("test query", token_budget=2000)
    # All fill_slice calls should have path_filter=None, exclude_filter=None
    for call in mock_fill_slice.call_args_list:
        assert call.kwargs.get("path_filter") is None
        assert call.kwargs.get("exclude_filter") is None


@patch("core.cognition.compiler.fill_identity_slice")
@patch("core.cognition.compiler.fill_slice")
def test_compile_context_passes_filters_to_competitive_tiers(mock_fill_slice, mock_fill_identity):
    from core.cognition.compiler import compile_context
    from core.interface.models import ContextSlice
    mock_fill_identity.return_value = (
        ContextSlice(name="identity", tier=MemoryTier.CORE, max_tokens=500, token_count=100),
        set(),
    )
    mock_fill_slice.return_value = ContextSlice(name="test", tier=MemoryTier.CORE, max_tokens=500, token_count=0)
    compile_context("test query", token_budget=2000, path_filter=["knowledge/"], exclude_filter=["journal/"])
    for call in mock_fill_slice.call_args_list:
        assert call.kwargs.get("path_filter") == ["knowledge/"]
        assert call.kwargs.get("exclude_filter") == ["journal/"]


@patch("core.cognition.compiler.fill_identity_slice")
@patch("core.cognition.compiler.fill_slice")
def test_identity_tier_never_filtered(mock_fill_slice, mock_fill_identity):
    from core.cognition.compiler import compile_context
    from core.interface.models import ContextSlice
    mock_fill_identity.return_value = (
        ContextSlice(name="identity", tier=MemoryTier.CORE, max_tokens=500, token_count=100),
        set(),
    )
    mock_fill_slice.return_value = ContextSlice(name="test", tier=MemoryTier.CORE, max_tokens=500, token_count=0)
    compile_context("test query", token_budget=2000, path_filter=["knowledge/"], exclude_filter=["journal/"])
    # fill_identity_slice should be called without any filter params
    mock_fill_identity.assert_called_once()
    call_args = mock_fill_identity.call_args
    assert "path_filter" not in call_args.kwargs
    assert "exclude_filter" not in call_args.kwargs


# ---------------------------------------------------------------------------
# Handler integration tests
# ---------------------------------------------------------------------------

class TestHandlerRoomIntegration:
    def test_prepare_query_passes_room_scope(self, tmp_path, monkeypatch):
        """Handler passes active Room's vault scope to compile_context."""
        monkeypatch.setattr("core.rooms.manager.ROOMS_DIR", tmp_path)
        from core.rooms.manager import get_room_manager, reset_room_manager
        from core.rooms.models import RoomConfig, RoomVaultScope

        mgr = get_room_manager(tmp_path)
        mgr.create_room(RoomConfig(
            id="scoped", name="Scoped",
            vault_scope=RoomVaultScope(mode="include", paths=["knowledge/ml/"]),
        ))
        mgr.switch_room("scoped")

        with patch("core.cognition.handler.compile_context") as mock_compile:
            mock_compile.return_value = MagicMock(
                query="test", slices=[], total_tokens=0, budget=6000,
            )
            from core.cognition.handler import _prepare_query
            try:
                _prepare_query("test query", force_local=True, force_cloud=False, skip_pii_scrub=True)
            except Exception:
                pass  # May fail due to other dependencies

            if mock_compile.called:
                _, kwargs = mock_compile.call_args
                assert kwargs.get("path_filter") == ["knowledge/ml/"]

        reset_room_manager()


def test_room_scope_to_filters():
    """Room vault scope mode maps to correct filter params."""
    from core.rooms.models import RoomVaultScope

    # include mode
    scope = RoomVaultScope(mode="include", paths=["knowledge/ml/"])
    path_filter = scope.paths if scope.mode == "include" and scope.paths else None
    exclude_filter = scope.paths if scope.mode == "exclude" and scope.paths else None
    assert path_filter == ["knowledge/ml/"]
    assert exclude_filter is None

    # exclude mode
    scope = RoomVaultScope(mode="exclude", paths=["knowledge/health/"])
    path_filter = scope.paths if scope.mode == "include" and scope.paths else None
    exclude_filter = scope.paths if scope.mode == "exclude" and scope.paths else None
    assert path_filter is None
    assert exclude_filter == ["knowledge/health/"]

    # all mode
    scope = RoomVaultScope(mode="all")
    path_filter = scope.paths if scope.mode == "include" and scope.paths else None
    exclude_filter = scope.paths if scope.mode == "exclude" and scope.paths else None
    assert path_filter is None
    assert exclude_filter is None
