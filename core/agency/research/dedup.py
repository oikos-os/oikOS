"""Vault dedup — check if a topic already exists in the vault."""

from __future__ import annotations

from core.memory.search import hybrid_search

DEFAULT_THRESHOLD = 0.85


def is_duplicate(topic: str, threshold: float = DEFAULT_THRESHOLD, limit: int = 3) -> bool:
    results = hybrid_search(topic, limit=limit)
    return any(r.final_score >= threshold for r in results)
