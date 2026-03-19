"""Tests for hybrid search."""

import math
import shutil
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from core.interface.config import EMBED_DIMS
from core.interface.models import MemoryTier, SearchResult
from core.memory.search import (
    _cosine_similarity,
    _dedup_episodic,
    _fetch_vectors,
    compute_recency_weight,
)


def test_recency_weight_recent():
    """Recent timestamp should have weight close to 1.0."""
    now = datetime.now(timezone.utc).isoformat()
    weight = compute_recency_weight(now)
    assert 0.95 <= weight <= 1.0


def test_recency_weight_old():
    """180-day-old timestamp should have weight near 0.25 (two half-lives)."""
    old = (datetime.now(timezone.utc) - timedelta(days=180)).isoformat()
    weight = compute_recency_weight(old)
    assert 0.2 <= weight <= 0.3


def test_recency_weight_half_life():
    """At exactly one half-life (90 days), weight should be ~0.5."""
    hl = (datetime.now(timezone.utc) - timedelta(days=90)).isoformat()
    weight = compute_recency_weight(hl)
    assert 0.45 <= weight <= 0.55


def test_recency_weight_invalid():
    """Invalid timestamp should return fallback 0.5."""
    weight = compute_recency_weight("not-a-date")
    assert weight == 0.5


# ── Cosine Similarity ─────────────────────────────────────────────────

def test_cosine_identical_vectors():
    vec = [1.0, 0.0, 0.5]
    assert abs(_cosine_similarity(vec, vec) - 1.0) < 1e-9


def test_cosine_orthogonal_vectors():
    a = [1.0, 0.0, 0.0]
    b = [0.0, 1.0, 0.0]
    assert abs(_cosine_similarity(a, b)) < 1e-9


def test_cosine_opposite_vectors():
    a = [1.0, 0.0]
    b = [-1.0, 0.0]
    assert abs(_cosine_similarity(a, b) - (-1.0)) < 1e-9


def test_cosine_zero_vector():
    a = [0.0, 0.0]
    b = [1.0, 2.0]
    assert _cosine_similarity(a, b) == 0.0


def test_cosine_similar_vectors():
    a = [1.0, 2.0, 3.0]
    b = [1.01, 2.01, 3.01]  # nearly identical
    sim = _cosine_similarity(a, b)
    assert sim > 0.999


# ── Episodic Dedup ─────────────────────────────────────────────────────

def _make_result(chunk_id: str, tier: MemoryTier, score: float) -> SearchResult:
    return SearchResult(
        chunk_id=chunk_id,
        source_path=f"vault/{chunk_id}.md",
        tier=tier,
        header_path="Test",
        content=f"Content for {chunk_id}",
        relevance_score=score,
        recency_weight=1.0,
        importance_weight=1.0,
        final_score=score,
    )


def _make_vec(base: float, dims: int = 10) -> list[float]:
    """Create a simple vector with given base value."""
    return [base + i * 0.01 for i in range(dims)]


@patch("core.memory.search._fetch_vectors")
def test_dedup_suppresses_near_duplicates(mock_fetch):
    """Two episodic chunks with >0.95 cosine sim → second suppressed."""
    vec_a = _make_vec(1.0)
    vec_b = [v + 0.0001 for v in vec_a]  # near-identical
    mock_fetch.return_value = {"ep-1": vec_a, "ep-2": vec_b}

    results = [
        _make_result("ep-1", MemoryTier.EPISODIC, 0.9),
        _make_result("ep-2", MemoryTier.EPISODIC, 0.8),
    ]
    deduped = _dedup_episodic(results, threshold=0.95)
    assert len(deduped) == 1
    assert deduped[0].chunk_id == "ep-1"


@patch("core.memory.search._fetch_vectors")
def test_dedup_keeps_dissimilar_episodic(mock_fetch):
    """Two episodic chunks with low similarity → both kept."""
    vec_a = [1.0, 0.0, 0.0, 0.0, 0.0]
    vec_b = [0.0, 1.0, 0.0, 0.0, 0.0]
    mock_fetch.return_value = {"ep-1": vec_a, "ep-2": vec_b}

    results = [
        _make_result("ep-1", MemoryTier.EPISODIC, 0.9),
        _make_result("ep-2", MemoryTier.EPISODIC, 0.8),
    ]
    deduped = _dedup_episodic(results, threshold=0.95)
    assert len(deduped) == 2


@patch("core.memory.search._fetch_vectors")
def test_dedup_ignores_non_episodic(mock_fetch):
    """Non-episodic results pass through even if content is identical."""
    mock_fetch.return_value = {}

    results = [
        _make_result("core-1", MemoryTier.CORE, 0.9),
        _make_result("sem-1", MemoryTier.SEMANTIC, 0.8),
    ]
    deduped = _dedup_episodic(results)
    assert len(deduped) == 2


@patch("core.memory.search._fetch_vectors")
def test_dedup_mixed_tiers(mock_fetch):
    """Only episodic duplicates suppressed; other tiers untouched."""
    vec_a = _make_vec(1.0)
    vec_b = [v + 0.0001 for v in vec_a]
    mock_fetch.return_value = {"ep-1": vec_a, "ep-2": vec_b}

    results = [
        _make_result("core-1", MemoryTier.CORE, 0.95),
        _make_result("ep-1", MemoryTier.EPISODIC, 0.9),
        _make_result("ep-2", MemoryTier.EPISODIC, 0.8),
        _make_result("sem-1", MemoryTier.SEMANTIC, 0.7),
    ]
    deduped = _dedup_episodic(results, threshold=0.95)
    assert len(deduped) == 3  # core-1, ep-1, sem-1
    ids = [r.chunk_id for r in deduped]
    assert "ep-2" not in ids
    assert "core-1" in ids


@patch("core.memory.search._fetch_vectors")
def test_dedup_single_episodic_passthrough(mock_fetch):
    """Single episodic result → no dedup needed, returned as-is."""
    mock_fetch.return_value = {}
    results = [_make_result("ep-1", MemoryTier.EPISODIC, 0.9)]
    deduped = _dedup_episodic(results)
    assert len(deduped) == 1


@patch("core.memory.search._fetch_vectors")
def test_dedup_empty_results(mock_fetch):
    mock_fetch.return_value = {}
    assert _dedup_episodic([]) == []


@patch("core.memory.search._fetch_vectors")
def test_dedup_missing_vector_kept(mock_fetch):
    """If vector lookup fails for a chunk, keep it (safe fallback)."""
    mock_fetch.return_value = {"ep-1": _make_vec(1.0)}  # ep-2 missing

    results = [
        _make_result("ep-1", MemoryTier.EPISODIC, 0.9),
        _make_result("ep-2", MemoryTier.EPISODIC, 0.8),
    ]
    deduped = _dedup_episodic(results, threshold=0.95)
    assert len(deduped) == 2  # both kept


@patch("core.memory.search._fetch_vectors")
def test_dedup_preserves_score_order(mock_fetch):
    """After dedup, results remain sorted by final_score descending."""
    vec_a = [1.0, 0.0, 0.0]
    vec_b = [0.0, 1.0, 0.0]
    mock_fetch.return_value = {"ep-1": vec_a, "ep-2": vec_b}

    results = [
        _make_result("sem-1", MemoryTier.SEMANTIC, 0.5),
        _make_result("ep-1", MemoryTier.EPISODIC, 0.9),
        _make_result("ep-2", MemoryTier.EPISODIC, 0.7),
    ]
    deduped = _dedup_episodic(results, threshold=0.95)
    scores = [r.final_score for r in deduped]
    assert scores == sorted(scores, reverse=True)


@patch("core.memory.search._fetch_vectors")
def test_dedup_three_duplicates_keeps_first(mock_fetch):
    """Three near-identical episodic chunks → only first (highest score) survives."""
    base = _make_vec(2.0, dims=5)
    mock_fetch.return_value = {
        "ep-1": base,
        "ep-2": [v + 0.00001 for v in base],
        "ep-3": [v + 0.00002 for v in base],
    }

    results = [
        _make_result("ep-1", MemoryTier.EPISODIC, 0.9),
        _make_result("ep-2", MemoryTier.EPISODIC, 0.85),
        _make_result("ep-3", MemoryTier.EPISODIC, 0.8),
    ]
    deduped = _dedup_episodic(results, threshold=0.95)
    assert len(deduped) == 1
    assert deduped[0].chunk_id == "ep-1"


# ── Integration: _fetch_vectors against real LanceDB ─────────────────

def test_fetch_vectors_real_lancedb():
    """Integration: _fetch_vectors retrieves stored vectors from a real LanceDB table."""
    import lancedb
    import pyarrow as pa

    db_dir = Path(tempfile.mkdtemp()) / "lancedb"
    db_dir.mkdir(parents=True, exist_ok=True)
    db = lancedb.connect(str(db_dir))

    schema = pa.schema([
        pa.field("chunk_id", pa.string()),
        pa.field("source_path", pa.string()),
        pa.field("tier", pa.string()),
        pa.field("header_path", pa.string()),
        pa.field("content", pa.string()),
        pa.field("file_mtime", pa.string()),
        pa.field("indexed_at", pa.string()),
        pa.field("vector", pa.list_(pa.float32(), EMBED_DIMS)),
    ])

    vec_a = [float(i) * 0.01 for i in range(EMBED_DIMS)]
    vec_b = [float(i) * 0.02 for i in range(EMBED_DIMS)]
    vec_c = [float(i) * 0.03 for i in range(EMBED_DIMS)]

    rows = [
        {"chunk_id": "test-1", "source_path": "a.md", "tier": "episodic",
         "header_path": "H1", "content": "c1", "file_mtime": "2026-01-01",
         "indexed_at": "2026-01-01", "vector": vec_a},
        {"chunk_id": "test-2", "source_path": "b.md", "tier": "episodic",
         "header_path": "H2", "content": "c2", "file_mtime": "2026-01-01",
         "indexed_at": "2026-01-01", "vector": vec_b},
        {"chunk_id": "test-3", "source_path": "c.md", "tier": "episodic",
         "header_path": "H3", "content": "c3", "file_mtime": "2026-01-01",
         "indexed_at": "2026-01-01", "vector": vec_c},
    ]

    db.create_table("vault_chunks", rows, schema=schema)

    with patch("core.memory.search.get_db", return_value=db):
        result = _fetch_vectors(["test-1", "test-3"])

    assert "test-1" in result
    assert "test-3" in result
    assert "test-2" not in result
    assert len(result["test-1"]) == EMBED_DIMS
    assert abs(result["test-1"][0] - 0.0) < 1e-6
    assert abs(result["test-1"][1] - 0.01) < 1e-6

    shutil.rmtree(db_dir.parent, ignore_errors=True)
