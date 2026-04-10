"""T-119: Notification API routes.

Mirrors the T-102 approval endpoint pattern. The NotificationManager
maintains an in-memory ring buffer of pending notifications. TUI and
web clients poll this endpoint.
"""
from __future__ import annotations

from fastapi import APIRouter, Query

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


@router.get("/pending")
def list_pending(
    since: float | None = Query(None, description="Return notifications newer than this Unix timestamp"),
) -> dict:
    """Return pending notifications as a JSON list.

    Non-destructive read — notifications stay in the buffer until they age
    out naturally (deque maxlen=50). Clients use the `since` parameter to
    paginate forward over time.
    """
    from core.autonomic.notifications import get_manager
    mgr = get_manager()
    items = mgr.drain_pending(since_timestamp=since)
    return {"pending": items}


@router.post("/reset")
def reset_session() -> dict:
    """Clear session state (dedup counters + pending buffer).

    Called automatically on session start; exposed here for manual reset.
    """
    from core.autonomic.notifications import get_manager
    mgr = get_manager()
    mgr.reset_session()
    return {"status": "reset"}
