"""Cosine sensitivity gate — embedding-based sovereign query detection."""

from __future__ import annotations

import logging
import math
import re
from pathlib import Path

from core.interface.config import (
    ROUTING_COSINE_ENTITY_DELTA,
    ROUTING_COSINE_SENSITIVITY_THRESHOLD,
    TABLE_NAME,
    VAULT_DIR,
)

log = logging.getLogger(__name__)

# Module-level cache (reset on re-index or process restart)
_identity_centroid: list[float] | None = None
_sovereign_entities: set[str] | None = None


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Cosine similarity between two vectors."""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def get_identity_centroid() -> list[float] | None:
    """Compute or return cached mean vector of identity-tier embeddings from LanceDB."""
    global _identity_centroid
    if _identity_centroid is not None:
        return _identity_centroid

    try:
        from core.memory.indexer import get_db, _table_exists

        db = get_db()
        if not _table_exists(db, TABLE_NAME):
            return None

        table = db.open_table(TABLE_NAME)
        rows = table.search().where("tier = 'core'").select(["vector"]).to_list()

        if not rows:
            return None

        # Compute centroid (element-wise mean)
        dims = len(rows[0]["vector"])
        centroid = [0.0] * dims
        for row in rows:
            for i, v in enumerate(row["vector"]):
                centroid[i] += v
        centroid = [c / len(rows) for c in centroid]

        _identity_centroid = centroid
        log.debug("Identity centroid computed from %d vectors.", len(rows))
        return _identity_centroid

    except Exception as e:
        log.debug("Failed to compute identity centroid: %s", e)
        return None


def invalidate_centroid_cache() -> None:
    """Clear cached centroid (call after re-index)."""
    global _identity_centroid
    _identity_centroid = None


def get_sovereign_entities() -> set[str]:
    """Extract proper nouns / project names from TELOS files for entity-based threshold modulation."""
    global _sovereign_entities
    if _sovereign_entities is not None:
        return _sovereign_entities

    entities: set[str] = set()

    # Extract project names from PROJECTS.md
    projects_file = VAULT_DIR / "identity" / "PROJECTS.md"
    if projects_file.exists():
        text = projects_file.read_text(encoding="utf-8")
        # Match markdown headers and bold items as project names
        for match in re.findall(r"(?:^#{1,3}\s+|^\*\*)([\w][\w\s\-']+?)(?:\*\*|\s*$)", text, re.MULTILINE):
            name = match.strip()
            if len(name) > 2:
                entities.add(name.lower())

    # Extract goal titles from GOALS.md
    goals_file = VAULT_DIR / "identity" / "GOALS.md"
    if goals_file.exists():
        text = goals_file.read_text(encoding="utf-8")
        for match in re.findall(r"^#{1,3}\s+([\w][\w\s\-']+)", text, re.MULTILINE):
            name = match.strip()
            if len(name) > 2:
                entities.add(name.lower())

    _sovereign_entities = entities
    log.debug("Loaded %d sovereign entities.", len(entities))
    return _sovereign_entities


def invalidate_entity_cache() -> None:
    """Clear cached entities (call after vault update)."""
    global _sovereign_entities
    _sovereign_entities = None


def check_sovereign_similarity(query_vector: list[float], query_text: str) -> bool:
    """Check if query is about sovereign data via cosine similarity to identity centroid.

    Returns True if the query should be forced local.
    Degrades gracefully: returns False if centroid unavailable.
    """
    centroid = get_identity_centroid()
    if centroid is None:
        return False

    similarity = cosine_similarity(query_vector, centroid)

    # Dynamic threshold modulation: lower threshold if sovereign entities detected
    threshold = ROUTING_COSINE_SENSITIVITY_THRESHOLD
    entities = get_sovereign_entities()
    query_lower = query_text.lower()

    if entities and any(entity in query_lower for entity in entities):
        threshold -= ROUTING_COSINE_ENTITY_DELTA
        log.debug("Entity detected in query — threshold lowered to %.2f", threshold)

    if similarity >= threshold:
        log.debug("Cosine sensitivity triggered: %.3f >= %.3f", similarity, threshold)
        return True

    return False
