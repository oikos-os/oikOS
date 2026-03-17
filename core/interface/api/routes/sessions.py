"""Session endpoints — close, list."""

from __future__ import annotations

from fastapi import APIRouter, Request

router = APIRouter()


@router.post("/session/close")
async def close_session(request: Request):
    """Close the current session. Accepts empty body (sendBeacon) or JSON."""
    reason = "browser_close"
    try:
        body = await request.body()
        if body:
            import json
            data = json.loads(body)
            reason = data.get("reason", reason)
    except Exception:
        pass

    from core.memory.session import close_session as _close
    result = _close(reason=reason)
    if result is None:
        return {"ok": True, "message": "No active session"}
    return {"ok": True, "session_id": result["session_id"]}
