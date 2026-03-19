import json
import pytest
from pathlib import Path
from unittest.mock import patch


class TestFrontmatterExtraction:
    def test_extracts_tags_list(self, tmp_path):
        md = tmp_path / "test.md"
        md.write_text("---\ntags: [ml, transformers, attention]\n---\n# Transformers\nContent here.", encoding="utf-8")
        from core.memory.chunker import chunk_markdown
        chunks = chunk_markdown(md)
        assert len(chunks) >= 1
        assert chunks[0].tags == ["ml", "transformers", "attention"]

    def test_no_frontmatter_empty_tags(self, tmp_path):
        md = tmp_path / "test.md"
        md.write_text("# No frontmatter\nJust content.", encoding="utf-8")
        from core.memory.chunker import chunk_markdown
        chunks = chunk_markdown(md)
        assert chunks[0].tags == []

    def test_frontmatter_without_tags_key(self, tmp_path):
        md = tmp_path / "test.md"
        md.write_text("---\ntitle: Test\n---\n# Test\nThis is enough content to pass the minimum chunk size filter.", encoding="utf-8")
        from core.memory.chunker import chunk_markdown
        chunks = chunk_markdown(md)
        assert chunks[0].tags == []

    def test_tags_as_comma_string(self, tmp_path):
        md = tmp_path / "test.md"
        md.write_text("---\ntags: ml, transformers\n---\n# Test\nThis is enough content to pass the minimum chunk size filter.", encoding="utf-8")
        from core.memory.chunker import chunk_markdown
        chunks = chunk_markdown(md)
        assert "ml" in chunks[0].tags
        assert "transformers" in chunks[0].tags

    def test_tags_propagate_to_all_chunks(self, tmp_path):
        md = tmp_path / "test.md"
        md.write_text("---\ntags: [ml]\n---\n# Section 1\nA\n# Section 2\nB", encoding="utf-8")
        from core.memory.chunker import chunk_markdown
        chunks = chunk_markdown(md)
        for chunk in chunks:
            assert chunk.tags == ["ml"]

    def test_malformed_yaml_returns_empty_tags(self, tmp_path):
        md = tmp_path / "test.md"
        md.write_text("---\n: [broken yaml\n---\n# Test\nThis is enough content to pass the minimum chunk size filter.", encoding="utf-8")
        from core.memory.chunker import chunk_markdown
        chunks = chunk_markdown(md)
        assert chunks[0].tags == []


class TestIndexerTagsColumn:
    def test_schema_includes_tags(self):
        from core.memory.indexer import SCHEMA
        field_names = [f.name for f in SCHEMA]
        assert "tags" in field_names

    def test_chunks_to_records_includes_tags(self):
        from core.interface.models import VaultChunk
        chunk = VaultChunk(
            chunk_id="test", source_path="test.md", tier="semantic",
            header_path="TEST", content="content", file_mtime="2026-01-01T00:00:00Z",
            tags=["ml", "transformers"],
        )
        with patch("core.memory.indexer.embed_batch", return_value=[[0.1]*768]):
            from core.memory.indexer import chunks_to_records
            records = chunks_to_records([chunk])
        assert records[0]["tags"] == '["ml", "transformers"]'

    def test_chunks_without_tags_get_empty_json(self):
        from core.interface.models import VaultChunk
        chunk = VaultChunk(
            chunk_id="test2", source_path="test2.md", tier="semantic",
            header_path="TEST", content="content", file_mtime="2026-01-01T00:00:00Z",
        )
        with patch("core.memory.indexer.embed_batch", return_value=[[0.1]*768]):
            from core.memory.indexer import chunks_to_records
            records = chunks_to_records([chunk])
        assert records[0]["tags"] == "[]"


from unittest.mock import MagicMock
from core.interface.models import MemoryTier, SearchResult


def _make_tag_row(chunk_id, source_path, tags_json="[]", score=0.8):
    return {
        "chunk_id": chunk_id, "source_path": source_path, "tier": "semantic",
        "header_path": f"TEST > {chunk_id}", "content": f"Content for {chunk_id}",
        "file_mtime": "2026-01-01T00:00:00Z", "tags": tags_json,
        "_relevance_score": score,
    }


def _setup_tag_mock_db(mock_get_db, rows):
    """Wire up mock_get_db with fluent builder returning rows."""
    mock_db = MagicMock()
    mock_get_db.return_value = mock_db
    mock_table = MagicMock()
    mock_db.open_table.return_value = mock_table
    mock_table.count_rows.return_value = len(rows)
    builder = MagicMock()
    mock_table.search.return_value = builder
    builder.vector.return_value = builder
    builder.text.return_value = builder
    builder.limit.return_value = builder
    builder.rerank.return_value = builder
    builder.where.return_value = builder
    builder.to_list.return_value = rows


class TestTagFiltering:
    @patch("core.memory.indexer._table_exists", return_value=True)
    @patch("core.memory.search.embed_single", return_value=[0.1]*768)
    @patch("core.memory.search.get_db")
    def test_tag_filter_none_returns_all(self, mock_db, mock_embed, mock_exists):
        rows = [_make_tag_row("a", "test/a.md", '["ml"]'), _make_tag_row("b", "test/b.md", '["health"]')]
        _setup_tag_mock_db(mock_db, rows)
        from core.memory.search import hybrid_search
        results = hybrid_search("test", tag_filter=None)
        assert len(results) == 2

    @patch("core.memory.indexer._table_exists", return_value=True)
    @patch("core.memory.search.embed_single", return_value=[0.1]*768)
    @patch("core.memory.search.get_db")
    def test_tag_filter_matches(self, mock_db, mock_embed, mock_exists):
        rows = [_make_tag_row("a", "test/a.md", '["ml", "transformers"]'), _make_tag_row("b", "test/b.md", '["health"]')]
        _setup_tag_mock_db(mock_db, rows)
        from core.memory.search import hybrid_search
        results = hybrid_search("test", tag_filter=["ml"])
        assert len(results) == 1
        assert results[0].chunk_id == "a"

    @patch("core.memory.indexer._table_exists", return_value=True)
    @patch("core.memory.search.embed_single", return_value=[0.1]*768)
    @patch("core.memory.search.get_db")
    def test_tag_filter_or_logic(self, mock_db, mock_embed, mock_exists):
        rows = [_make_tag_row("a", "test/a.md", '["ml"]'), _make_tag_row("b", "test/b.md", '["health"]'), _make_tag_row("c", "test/c.md", '["nlp"]')]
        _setup_tag_mock_db(mock_db, rows)
        from core.memory.search import hybrid_search
        results = hybrid_search("test", tag_filter=["ml", "nlp"])
        assert len(results) == 2

    @patch("core.memory.indexer._table_exists", return_value=True)
    @patch("core.memory.search.embed_single", return_value=[0.1]*768)
    @patch("core.memory.search.get_db")
    def test_empty_tag_filter_returns_nothing(self, mock_db, mock_embed, mock_exists):
        rows = [_make_tag_row("a", "test/a.md", '["ml"]')]
        _setup_tag_mock_db(mock_db, rows)
        from core.memory.search import hybrid_search
        results = hybrid_search("test", tag_filter=[])
        assert len(results) == 0

    @patch("core.memory.indexer._table_exists", return_value=True)
    @patch("core.memory.search.embed_single", return_value=[0.1]*768)
    @patch("core.memory.search.get_db")
    def test_no_tags_file_excluded(self, mock_db, mock_embed, mock_exists):
        rows = [_make_tag_row("a", "test/a.md", "[]")]
        _setup_tag_mock_db(mock_db, rows)
        from core.memory.search import hybrid_search
        results = hybrid_search("test", tag_filter=["ml"])
        assert len(results) == 0

    def test_compile_context_passes_tag_filter(self):
        with patch("core.cognition.compiler.search_tier") as mock_search:
            mock_search.return_value = []
            from core.cognition.compiler import compile_context
            compile_context("test", tag_filter=["ml"])
            calls_with_tag = [c for c in mock_search.call_args_list if c.kwargs.get("tag_filter") == ["ml"]]
            assert len(calls_with_tag) > 0
