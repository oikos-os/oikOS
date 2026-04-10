"""Vault endpoints — stats."""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()


@router.get("/stats")
def vault_stats():
    from core.memory.indexer import get_table_stats

    return get_table_stats()
