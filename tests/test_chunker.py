"""Tests for the markdown chunker."""

import tempfile
from pathlib import Path

from core.memory.chunker import (
    chunk_markdown,
    classify_tier,
    discover_vault_files,
    make_chunk_id,
)
from core.interface.config import VAULT_DIR
from core.interface.models import MemoryTier


def test_classify_tier_identity():
    path = VAULT_DIR / "identity" / "MISSION.md"
    assert classify_tier(path) == MemoryTier.CORE


def test_classify_tier_patterns():
    path = VAULT_DIR / "patterns" / "compile_context" / "system.md"
    assert classify_tier(path) == MemoryTier.PROCEDURAL


def test_classify_tier_knowledge():
    path = VAULT_DIR / "knowledge" / "notes.md"
    assert classify_tier(path) == MemoryTier.SEMANTIC


def test_deterministic_chunk_ids():
    id1 = make_chunk_id("vault/identity/GOALS.md", "Goals > Short-Term", 0)
    id2 = make_chunk_id("vault/identity/GOALS.md", "Goals > Short-Term", 0)
    id3 = make_chunk_id("vault/identity/GOALS.md", "Goals > Long-Term", 1)
    assert id1 == id2  # same inputs → same ID
    assert id1 != id3  # different inputs → different ID
    assert len(id1) == 16


def test_chunk_heading_splitting():
    md = "# Title\n\nSome content here about the title.\n\n## Section A\n\nContent for section A with enough text.\n\n## Section B\n\nContent for section B with enough text.\n"
    with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False, encoding="utf-8") as f:
        f.write(md)
        f.flush()
        chunks = chunk_markdown(Path(f.name))

    assert len(chunks) == 3
    assert chunks[0].header_path == "Title"
    assert chunks[1].header_path == "Title > Section A"
    assert chunks[2].header_path == "Title > Section B"


def test_chunk_nested_headings():
    md = "# Root\n\nRoot content with meaningful text.\n\n## Child\n\nChild content with meaningful text.\n\n### Grandchild\n\nGrandchild content with meaningful text.\n"
    with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False, encoding="utf-8") as f:
        f.write(md)
        f.flush()
        chunks = chunk_markdown(Path(f.name))

    headers = [c.header_path for c in chunks]
    assert "Root" in headers
    assert "Root > Child" in headers
    assert "Root > Child > Grandchild" in headers


def test_chunk_empty_template_skipped():
    """TELOS templates with only headings and HTML comments should produce no chunks."""
    md = "# Title\n\n<!-- Fill this in -->\n\n## Section\n\n<!-- TODO -->\n"
    with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False, encoding="utf-8") as f:
        f.write(md)
        f.flush()
        chunks = chunk_markdown(Path(f.name))

    assert len(chunks) == 0


def test_chunk_preamble():
    md = "This is preamble text before any heading, long enough to pass the minimum.\n\n# First Heading\n\nContent under first heading with enough text.\n"
    with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False, encoding="utf-8") as f:
        f.write(md)
        f.flush()
        chunks = chunk_markdown(Path(f.name))

    assert chunks[0].header_path == "(preamble)"
    assert "preamble text" in chunks[0].content


def test_discover_vault_files():
    files = discover_vault_files()
    assert len(files) > 0
    assert all(f.suffix == ".md" for f in files)
    assert all(f.name != ".gitkeep" for f in files)
