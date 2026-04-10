"""Search endpoint — queries vault memory via hybrid search."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Query

log = logging.getLogger(__name__)
router = APIRouter()


@router.get("/search")
def search_vault(q: str = Query(..., min_length=1), limit: int = Query(10, ge=1, le=50)):
    try:
        from core.memory.search import hybrid_search
        results = hybrid_search(q, limit=limit)
        return {
            "query": q,
            "results": [
                {
                    "content": r.content,
                    "source_path": r.source_path,
                    "score": round(r.final_score, 3) if r.final_score else None,
                    "tier": r.tier.value if r.tier else None,
                }
                for r in results
            ],
            "count": len(results),
        }
    except Exception as exc:
        log.error("Search failed: %s: %s", type(exc).__name__, exc)
        return {"query": q, "results": [], "count": 0, "error": "Search unavailable"}
