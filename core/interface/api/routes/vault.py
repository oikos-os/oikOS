"""Vault endpoints — stats, search."""

from __future__ import annotations

from fastapi import APIRouter, Query

router = APIRouter()


@router.get("/stats")
def vault_stats():
    from core.memory.indexer import get_table_stats

    return get_table_stats()


@router.get("/search")
def vault_search(q: str = Query(..., min_length=1), limit: int = Query(10, ge=1, le=100)):
    from core.memory.search import hybrid_search

    results = hybrid_search(q, limit=limit)
    return [
        {
            "content": r.content,
            "source_path": r.source_path,
            "header_path": r.header_path,
            "tier": r.tier.value,
            "final_score": r.final_score,
        }
        for r in results
    ]
