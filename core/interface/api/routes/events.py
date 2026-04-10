"""Event feed endpoint — tails logs/events.jsonl."""

from __future__ import annotations

from fastapi import APIRouter, Query

router = APIRouter()


@router.get("/events")
def get_events(since: str | None = Query(None), limit: int = Query(50, ge=1, le=500)):
    from core.autonomic.events import read_events

    return read_events(since=since, limit=limit)
