"""Hybrid BM25+vector search with tier-aware weighted scoring."""

from __future__ import annotations

import logging
import math
from datetime import datetime, timezone

from lancedb.rerankers import RRFReranker

from core.interface.config import (
    DEFAULT_SEARCH_LIMIT,
    EPISODIC_DEDUP_THRESHOLD,
    HYBRID_WEIGHT,
    RECENCY_HALF_LIFE_DAYS,
    TABLE_NAME,
)
from core.memory.embedder import embed_single
from core.memory.indexer import get_db
from core.interface.models import TIER_IMPORTANCE, MemoryTier, SearchResult

log = logging.getLogger(__name__)


def compute_recency_weight(iso_timestamp: str) -> float:
    """Exponential decay weight based on age. Half-life = RECENCY_HALF_LIFE_DAYS."""
    try:
        ts = datetime.fromisoformat(iso_timestamp)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        age_days = (datetime.now(timezone.utc) - ts).total_seconds() / 86400
        return math.exp(-0.693 * age_days / RECENCY_HALF_LIFE_DAYS)  # ln(2) ≈ 0.693
    except Exception:
        return 0.5  # fallback for unparseable timestamps


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Cosine similarity between two equal-length vectors."""
    dot = sum(x * y for x, y in zip(a, b))
    mag_a = math.sqrt(sum(x * x for x in a))
    mag_b = math.sqrt(sum(x * x for x in b))
    if mag_a == 0 or mag_b == 0:
        return 0.0
    return dot / (mag_a * mag_b)


def _dedup_episodic(
    results: list[SearchResult],
    threshold: float = EPISODIC_DEDUP_THRESHOLD,
) -> list[SearchResult]:
    """Suppress near-duplicate episodic chunks (>threshold cosine similarity).

    Non-episodic results pass through unchanged. Episodic results are checked
    against already-accepted episodic chunks; duplicates are dropped.
    Vectors are retrieved from LanceDB by chunk_id to avoid re-embedding.
    """
    # Separate episodic from non-episodic
    non_episodic = [r for r in results if r.tier != MemoryTier.EPISODIC]
    episodic = [r for r in results if r.tier == MemoryTier.EPISODIC]

    if len(episodic) <= 1:
        return results

    # Fetch vectors for episodic chunks from the index
    episodic_vecs = _fetch_vectors([r.chunk_id for r in episodic])

    accepted: list[SearchResult] = []
    accepted_vecs: list[list[float]] = []

    for result in episodic:
        vec = episodic_vecs.get(result.chunk_id)
        if vec is None:
            # No vector found — keep the result (safe fallback)
            accepted.append(result)
            continue

        # Check against all already-accepted episodic chunks
        is_dup = any(
            _cosine_similarity(vec, av) > threshold for av in accepted_vecs
        )
        if not is_dup:
            accepted.append(result)
            accepted_vecs.append(vec)
        else:
            log.debug("Episodic dedup: suppressed %s (>%.2f sim)", result.chunk_id, threshold)

    # Recombine: non-episodic + deduped episodic, preserve original score order
    combined = non_episodic + accepted
    combined.sort(key=lambda r: r.final_score, reverse=True)
    return combined


def _fetch_vectors(chunk_ids: list[str]) -> dict[str, list[float]]:
    """Retrieve stored embedding vectors for given chunk IDs from LanceDB."""
    if not chunk_ids:
        return {}
    db = get_db()
    from core.memory.indexer import _table_exists

    if not _table_exists(db, TABLE_NAME):
        return {}

    table = db.open_table(TABLE_NAME)
    id_list = ", ".join(f"'{cid}'" for cid in chunk_ids)
    try:
        rows = (
            table.search()
            .where(f"chunk_id IN ({id_list})")
            .select(["chunk_id", "vector"])
            .limit(len(chunk_ids))
            .to_list()
        )
        return {
            row["chunk_id"]: list(row["vector"]) for row in rows
        }
    except Exception as e:
        log.warning("Failed to fetch vectors for dedup: %s", e)
        return {}


def hybrid_search(
    query: str,
    limit: int = DEFAULT_SEARCH_LIMIT,
    tier_filter: MemoryTier | None = None,
    hybrid_weight: float = HYBRID_WEIGHT,
) -> list[SearchResult]:
    """Run hybrid BM25+vector search with custom scoring.

    Over-fetches 2x limit, then applies: final = relevance * recency * importance.
    """
    db = get_db()
    from core.memory.indexer import _table_exists

    if not _table_exists(db, TABLE_NAME):
        return []

    table = db.open_table(TABLE_NAME)

    # Check table has rows
    if table.count_rows() == 0:
        return []

    # Embed query
    query_vec = embed_single(query)

    # Build hybrid search
    reranker = RRFReranker()
    search_builder = table.search(query_type="hybrid")
    search_builder = search_builder.vector(query_vec)
    search_builder = search_builder.text(query)
    search_builder = search_builder.limit(limit * 2)  # over-fetch
    search_builder = search_builder.rerank(reranker)

    if tier_filter is not None:
        search_builder = search_builder.where(f"tier = '{tier_filter.value}'")

    try:
        results = search_builder.to_list()
    except Exception as e:
        log.warning("Hybrid search failed, falling back to vector-only: %s", e)
        # Fallback: vector-only search
        search_builder = table.search(query_vec).limit(limit * 2)
        if tier_filter is not None:
            search_builder = search_builder.where(f"tier = '{tier_filter.value}'")
        results = search_builder.to_list()

    # Score and rank
    scored: list[SearchResult] = []
    for row in results:
        relevance = max(1.0 - row.get("_distance", 0.0), 0.01) if "_distance" in row else row.get("_relevance_score", 0.5)
        tier = MemoryTier(row["tier"])
        recency = compute_recency_weight(row["file_mtime"])
        importance = TIER_IMPORTANCE.get(tier, 1.0)
        final = relevance * recency * importance

        scored.append(
            SearchResult(
                chunk_id=row["chunk_id"],
                source_path=row["source_path"],
                tier=tier,
                header_path=row["header_path"],
                content=row["content"],
                relevance_score=relevance,
                recency_weight=recency,
                importance_weight=importance,
                final_score=final,
            )
        )

    scored.sort(key=lambda r: r.final_score, reverse=True)
    truncated = scored[:limit]

    # Session-aware dedup: suppress near-duplicate episodic chunks
    return _dedup_episodic(truncated)


def search_tier(
    query: str,
    tier: MemoryTier,
    limit: int = DEFAULT_SEARCH_LIMIT,
) -> list[SearchResult]:
    """Convenience: search within a single tier."""
    return hybrid_search(query, limit=limit, tier_filter=tier)
