"""Tests for LanceDB index management."""

import shutil
import tempfile
from pathlib import Path
from unittest.mock import patch

from core.interface.config import EMBED_DIMS
from core.memory.indexer import (
    get_db,
    get_or_create_table,
    get_table_stats,
    index_vault,
)


def _fake_embed_batch(texts):
    return [[0.1] * EMBED_DIMS for _ in texts]


@patch("core.memory.indexer.LANCEDB_DIR", Path(tempfile.mkdtemp()) / "lancedb")
def test_get_or_create_table():
    table = get_or_create_table()
    assert table is not None
    assert table.count_rows() == 0


@patch("core.memory.indexer.embed_batch", side_effect=_fake_embed_batch)
@patch("core.memory.indexer.LANCEDB_DIR", Path(tempfile.mkdtemp()) / "lancedb")
def test_full_rebuild(mock_embed):
    stats = index_vault(full_rebuild=True)
    assert stats["files"] > 0
    assert stats["added"] >= 0  # may be 0 if all templates are empty
    assert stats["skipped"] == 0


@patch("core.memory.indexer.embed_batch", side_effect=_fake_embed_batch)
@patch("core.memory.indexer.LANCEDB_DIR", Path(tempfile.mkdtemp()) / "lancedb")
def test_incremental_skips_unchanged(mock_embed):
    # First run indexes everything
    stats1 = index_vault(full_rebuild=True)
    added_first = stats1["added"]

    # Second run should skip all (no mtime changes)
    stats2 = index_vault(full_rebuild=False)
    assert stats2["skipped"] == stats2["files"]
    assert stats2["added"] == 0


@patch("core.memory.indexer.embed_batch", side_effect=_fake_embed_batch)
@patch("core.memory.indexer.LANCEDB_DIR", Path(tempfile.mkdtemp()) / "lancedb")
def test_table_stats(mock_embed):
    index_vault(full_rebuild=True)
    stats = get_table_stats()
    assert "total_rows" in stats
    assert "unique_files" in stats
    assert "tier_breakdown" in stats
