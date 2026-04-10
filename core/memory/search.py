"""Hybrid BM25+vector search with tier-aware weighted scoring."""

from __future__ import annotations

import json
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
from core.memory.embedder_registry import EmbedderRegistry
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
        return math.exp(-math.log(2) * age_days / RECENCY_HALF_LIFE_DAYS)
    except Exception as e:
        log.debug("Recency weight failed for timestamp: %s", e)
        return 0.5  # fallback for unparseable timestamps


from core.utils.math import cosine_similarity as _cosine_similarity


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
    path_filter: list[str] | None = None,
    exclude_filter: list[str] | None = None,
    tag_filter: list[str] | None = None,
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

    # Embed query — None means embedder unavailable
    registry = EmbedderRegistry.get_instance()
    query_vec = registry.embed_single_safe(query)

    fetch_mult = 3 if (path_filter or exclude_filter or tag_filter) else 2

    if query_vec is not None:
        # ── Hybrid path (vector + text + RRF reranker) ───────────────
        reranker = RRFReranker()
        search_builder = table.search(query_type="hybrid")
        search_builder = search_builder.vector(query_vec)
        search_builder = search_builder.text(query)
        search_builder = search_builder.limit(limit * fetch_mult)  # over-fetch
        search_builder = search_builder.rerank(reranker)

        if tier_filter is not None:
            search_builder = search_builder.where(f"tier = '{tier_filter.value}'")

        try:
            results = search_builder.to_list()
        except Exception as e:
            log.warning("Hybrid search failed, falling back to vector-only: %s", e)
            # Fallback: vector-only search (still uses embeddings)
            search_builder = table.search(query_vec).limit(limit * fetch_mult)
            if tier_filter is not None:
                search_builder = search_builder.where(f"tier = '{tier_filter.value}'")
            results = search_builder.to_list()
    else:
        # ── BM25-only fallback (no embedder available) ───────────────
        log.warning("Embedder unavailable — falling back to BM25-only search")
        search_builder = table.search(query, query_type="fts").limit(limit * fetch_mult)
        if tier_filter is not None:
            search_builder = search_builder.where(f"tier = '{tier_filter.value}'")
        try:
            results = search_builder.to_list()
        except Exception as e:
            log.warning("FTS search also failed: %s — returning empty", e)
            results = []

    # Score and rank
    scored: list[SearchResult] = []
    for row in results:
        if "_distance" in row:
            relevance = max(1.0 - row["_distance"], 0.01)
        elif "_relevance_score" in row:
            relevance = row["_relevance_score"]
        elif "_score" in row:
            relevance = min(row["_score"] / 10.0, 1.0)  # BM25 normalization
        else:
            relevance = 0.5
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

    # Tag lookup for post-query filtering
    tag_lookup: dict[str, list[str]] = {}
    if tag_filter is not None:
        for row in results:
            tags_raw = row.get("tags", "[]")
            try:
                tag_lookup[row["chunk_id"]] = json.loads(tags_raw) if isinstance(tags_raw, str) else []
            except (json.JSONDecodeError, TypeError):
                tag_lookup[row["chunk_id"]] = []

    if path_filter is not None:
        normalized = [p.replace("\\", "/") for p in path_filter]
        scored = [r for r in scored if any(r.source_path.replace("\\", "/").startswith(p) for p in normalized)]
    if exclude_filter is not None:
        normalized = [p.replace("\\", "/") for p in exclude_filter]
        scored = [r for r in scored if not any(r.source_path.replace("\\", "/").startswith(p) for p in normalized)]

    if tag_filter is not None:
        tag_set = set(tag_filter)
        scored = [r for r in scored if tag_set.intersection(tag_lookup.get(r.chunk_id, []))]

    truncated = scored[:limit]

    # Session-aware dedup: suppress near-duplicate episodic chunks
    return _dedup_episodic(truncated)


def search_tier(
    query: str,
    tier: MemoryTier,
    limit: int = DEFAULT_SEARCH_LIMIT,
    path_filter: list[str] | None = None,
    exclude_filter: list[str] | None = None,
    tag_filter: list[str] | None = None,
) -> list[SearchResult]:
    """Convenience: search within a single tier."""
    return hybrid_search(query, limit=limit, tier_filter=tier, path_filter=path_filter, exclude_filter=exclude_filter, tag_filter=tag_filter)
