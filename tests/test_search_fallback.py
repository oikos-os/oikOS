"""Tests for BM25 fallback when embedder is unavailable."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from core.interface.models import MemoryTier, SearchResult
from core.memory.embedder_registry import EmbedderRegistry


# ── Helpers ──────────────────────────────────────────────────────────────

def _make_fts_row(chunk_id: str, score: float, tier: str = "semantic") -> dict:
    """Build a fake LanceDB FTS result row with _score field."""
    return {
        "chunk_id": chunk_id,
        "source_path": f"vault/{chunk_id}.md",
        "tier": tier,
        "header_path": "Test",
        "content": f"Content for {chunk_id}",
        "file_mtime": datetime.now(timezone.utc).isoformat(),
        "_score": score,
    }


def _make_hybrid_row(chunk_id: str, relevance: float, tier: str = "semantic") -> dict:
    """Build a fake LanceDB hybrid result row with _relevance_score."""
    return {
        "chunk_id": chunk_id,
        "source_path": f"vault/{chunk_id}.md",
        "tier": tier,
        "header_path": "Test",
        "content": f"Content for {chunk_id}",
        "file_mtime": datetime.now(timezone.utc).isoformat(),
        "_relevance_score": relevance,
    }


def _make_distance_row(chunk_id: str, distance: float, tier: str = "semantic") -> dict:
    """Build a fake LanceDB vector result row with _distance."""
    return {
        "chunk_id": chunk_id,
        "source_path": f"vault/{chunk_id}.md",
        "tier": tier,
        "header_path": "Test",
        "content": f"Content for {chunk_id}",
        "file_mtime": datetime.now(timezone.utc).isoformat(),
        "_distance": distance,
    }


# ── Fixtures ─────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _reset_registry():
    """Ensure clean EmbedderRegistry state for each test."""
    EmbedderRegistry.reset()
    yield
    EmbedderRegistry.reset()


# ── BM25 Fallback Tests ─────────────────────────────────────────────────

@patch("core.memory.indexer._table_exists", return_value=True)
@patch("core.memory.search.get_db")
def test_bm25_fallback_when_no_embedder(mock_get_db, mock_table_exists):
    """With no embedder registered, hybrid_search should NOT crash and should
    attempt FTS search instead of vector search."""
    # No embedder registered — EmbedderRegistry.embed_single_safe returns None

    mock_table = MagicMock()
    mock_table.count_rows.return_value = 10

    # FTS search chain
    mock_fts_builder = MagicMock()
    mock_table.search.return_value = mock_fts_builder
    mock_fts_builder.limit.return_value = mock_fts_builder
    mock_fts_builder.to_list.return_value = [
        _make_fts_row("chunk-1", 8.5),
        _make_fts_row("chunk-2", 5.2),
    ]

    mock_db = MagicMock()
    mock_db.open_table.return_value = mock_table
    mock_get_db.return_value = mock_db

    from core.memory.search import hybrid_search

    results = hybrid_search("test query", limit=5)

    # Should not crash, should return results
    assert len(results) == 2
    assert results[0].chunk_id == "chunk-1"
    assert results[1].chunk_id == "chunk-2"

    # Verify FTS path was used (query_type="fts")
    mock_table.search.assert_called_once_with("test query", query_type="fts")


@patch("core.memory.indexer._table_exists", return_value=True)
@patch("core.memory.search.get_db")
def test_bm25_fallback_with_tier_filter(mock_get_db, mock_table_exists):
    """BM25 fallback should apply tier filter when specified."""
    mock_table = MagicMock()
    mock_table.count_rows.return_value = 10

    mock_fts_builder = MagicMock()
    mock_table.search.return_value = mock_fts_builder
    mock_fts_builder.limit.return_value = mock_fts_builder
    mock_fts_builder.where.return_value = mock_fts_builder
    mock_fts_builder.to_list.return_value = [
        _make_fts_row("chunk-1", 7.0, "core"),
    ]

    mock_db = MagicMock()
    mock_db.open_table.return_value = mock_table
    mock_get_db.return_value = mock_db

    from core.memory.search import hybrid_search

    results = hybrid_search("test query", limit=5, tier_filter=MemoryTier.CORE)

    assert len(results) == 1
    # Verify .where() was called for tier filtering
    mock_fts_builder.where.assert_called_once_with("tier = 'core'")


@patch("core.memory.indexer._table_exists", return_value=True)
@patch("core.memory.search.get_db")
def test_bm25_fallback_fts_also_fails(mock_get_db, mock_table_exists):
    """If FTS search also fails, return empty list instead of crashing."""
    mock_table = MagicMock()
    mock_table.count_rows.return_value = 10

    mock_fts_builder = MagicMock()
    mock_table.search.return_value = mock_fts_builder
    mock_fts_builder.limit.return_value = mock_fts_builder
    mock_fts_builder.to_list.side_effect = Exception("FTS index not found")

    mock_db = MagicMock()
    mock_db.open_table.return_value = mock_table
    mock_get_db.return_value = mock_db

    from core.memory.search import hybrid_search

    results = hybrid_search("test query", limit=5)
    assert results == []


# ── Scoring Tests ────────────────────────────────────────────────────────

@patch("core.memory.indexer._table_exists", return_value=True)
@patch("core.memory.search.get_db")
def test_bm25_score_normalization(mock_get_db, mock_table_exists):
    """Verify _score from BM25 is normalized: score/10, capped at 1.0."""
    mock_table = MagicMock()
    mock_table.count_rows.return_value = 10

    mock_fts_builder = MagicMock()
    mock_table.search.return_value = mock_fts_builder
    mock_fts_builder.limit.return_value = mock_fts_builder
    mock_fts_builder.to_list.return_value = [
        _make_fts_row("low", 3.0),    # 3.0 / 10 = 0.3
        _make_fts_row("high", 15.0),  # 15.0 / 10 = 1.5 -> capped to 1.0
        _make_fts_row("mid", 7.0),    # 7.0 / 10 = 0.7
    ]

    mock_db = MagicMock()
    mock_db.open_table.return_value = mock_table
    mock_get_db.return_value = mock_db

    from core.memory.search import hybrid_search

    results = hybrid_search("test query", limit=10)

    scores = {r.chunk_id: r.relevance_score for r in results}
    assert abs(scores["low"] - 0.3) < 0.01
    assert abs(scores["high"] - 1.0) < 0.01  # capped
    assert abs(scores["mid"] - 0.7) < 0.01


@patch("core.memory.indexer._table_exists", return_value=True)
@patch("core.memory.search.get_db")
def test_distance_scoring_still_works(mock_get_db, mock_table_exists):
    """Verify _distance scoring path still works (regression check)."""
    # Register a mock embedder so the hybrid path is taken
    mock_embedder = MagicMock()
    mock_embedder.is_available.return_value = True
    mock_embedder.embed_single.return_value = [0.1] * 768

    registry = EmbedderRegistry.get_instance()
    registry.register(mock_embedder)

    mock_table = MagicMock()
    mock_table.count_rows.return_value = 10

    mock_search_builder = MagicMock()
    mock_table.search.return_value = mock_search_builder
    mock_search_builder.vector.return_value = mock_search_builder
    mock_search_builder.text.return_value = mock_search_builder
    mock_search_builder.limit.return_value = mock_search_builder
    mock_search_builder.rerank.return_value = mock_search_builder
    mock_search_builder.where.return_value = mock_search_builder
    mock_search_builder.to_list.return_value = [
        _make_distance_row("d-1", 0.2),  # relevance = 1.0 - 0.2 = 0.8
    ]

    mock_db = MagicMock()
    mock_db.open_table.return_value = mock_table
    mock_get_db.return_value = mock_db

    from core.memory.search import hybrid_search

    results = hybrid_search("test query", limit=5)
    assert len(results) == 1
    assert abs(results[0].relevance_score - 0.8) < 0.01


@patch("core.memory.indexer._table_exists", return_value=True)
@patch("core.memory.search.get_db")
def test_hybrid_still_works_with_embedder(mock_get_db, mock_table_exists):
    """With a working embedder, the full hybrid path (vector + text + RRF) is used."""
    mock_embedder = MagicMock()
    mock_embedder.is_available.return_value = True
    mock_embedder.embed_single.return_value = [0.1] * 768

    registry = EmbedderRegistry.get_instance()
    registry.register(mock_embedder)

    mock_table = MagicMock()
    mock_table.count_rows.return_value = 10

    mock_search_builder = MagicMock()
    mock_table.search.return_value = mock_search_builder
    mock_search_builder.vector.return_value = mock_search_builder
    mock_search_builder.text.return_value = mock_search_builder
    mock_search_builder.limit.return_value = mock_search_builder
    mock_search_builder.rerank.return_value = mock_search_builder
    mock_search_builder.where.return_value = mock_search_builder
    mock_search_builder.to_list.return_value = [
        _make_hybrid_row("h-1", 0.9),
        _make_hybrid_row("h-2", 0.7),
    ]

    mock_db = MagicMock()
    mock_db.open_table.return_value = mock_table
    mock_get_db.return_value = mock_db

    from core.memory.search import hybrid_search

    results = hybrid_search("test query", limit=5)
    assert len(results) == 2

    # Verify hybrid path was used (query_type="hybrid")
    mock_table.search.assert_called_once_with(query_type="hybrid")
    # Verify vector() was called with embedder output
    mock_search_builder.vector.assert_called_once()


@patch("core.memory.indexer._table_exists", return_value=True)
@patch("core.memory.search.get_db")
def test_hybrid_vector_fallback_when_hybrid_fails(mock_get_db, mock_table_exists):
    """When hybrid search fails but embedder is available, fall back to vector-only,
    NOT to BM25-only."""
    mock_embedder = MagicMock()
    mock_embedder.is_available.return_value = True
    mock_embedder.embed_single.return_value = [0.1] * 768

    registry = EmbedderRegistry.get_instance()
    registry.register(mock_embedder)

    mock_table = MagicMock()
    mock_table.count_rows.return_value = 10

    # First call (hybrid) raises, second call (vector-only) succeeds
    mock_hybrid_builder = MagicMock()
    mock_hybrid_builder.vector.return_value = mock_hybrid_builder
    mock_hybrid_builder.text.return_value = mock_hybrid_builder
    mock_hybrid_builder.limit.return_value = mock_hybrid_builder
    mock_hybrid_builder.rerank.return_value = mock_hybrid_builder
    mock_hybrid_builder.where.return_value = mock_hybrid_builder
    mock_hybrid_builder.to_list.side_effect = Exception("hybrid search error")

    # Vector-only fallback builder
    mock_vector_builder = MagicMock()
    mock_vector_builder.limit.return_value = mock_vector_builder
    mock_vector_builder.where.return_value = mock_vector_builder
    mock_vector_builder.to_list.return_value = [
        _make_distance_row("v-1", 0.3),
    ]

    # First call: table.search(query_type="hybrid") -> hybrid builder
    # Second call: table.search(query_vec) -> vector builder
    call_count = [0]

    def search_side_effect(*args, **kwargs):
        call_count[0] += 1
        if call_count[0] == 1:
            return mock_hybrid_builder
        else:
            return mock_vector_builder

    mock_table.search = MagicMock(side_effect=search_side_effect)

    mock_db = MagicMock()
    mock_db.open_table.return_value = mock_table
    mock_get_db.return_value = mock_db

    from core.memory.search import hybrid_search

    results = hybrid_search("test query", limit=5)
    assert len(results) == 1
    assert results[0].chunk_id == "v-1"


# ── Edge case: no score fields ──────────────────────────────────────────

@patch("core.memory.indexer._table_exists", return_value=True)
@patch("core.memory.search.get_db")
def test_no_score_fields_uses_default(mock_get_db, mock_table_exists):
    """Row with no recognized score field gets default relevance of 0.5."""
    mock_table = MagicMock()
    mock_table.count_rows.return_value = 10

    mock_fts_builder = MagicMock()
    mock_table.search.return_value = mock_fts_builder
    mock_fts_builder.limit.return_value = mock_fts_builder
    mock_fts_builder.to_list.return_value = [{
        "chunk_id": "bare",
        "source_path": "vault/bare.md",
        "tier": "semantic",
        "header_path": "Test",
        "content": "No score fields",
        "file_mtime": datetime.now(timezone.utc).isoformat(),
        # No _distance, _relevance_score, or _score
    }]

    mock_db = MagicMock()
    mock_db.open_table.return_value = mock_table
    mock_get_db.return_value = mock_db

    from core.memory.search import hybrid_search

    results = hybrid_search("test query", limit=5)
    assert len(results) == 1
    assert abs(results[0].relevance_score - 0.5) < 0.01
