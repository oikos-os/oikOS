"""WebSocket heartbeat — pushes daemon + FSM state + pending proposals every 30s."""

from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from core.interface.api.auth import validate_ws_token
from core.interface.config import APPROVAL_PROPOSALS_LOG

log = logging.getLogger(__name__)

router = APIRouter()


_SENSITIVE_ARG_KEYS = frozenset({"content", "password", "secret", "token", "key"})


def _redact_tool_args(args: dict) -> dict:
    """Replace values for sensitive keys with [REDACTED]."""
    return {
        k: "[REDACTED]" if any(s in k.lower() for s in _SENSITIVE_ARG_KEYS) else v
        for k, v in args.items()
    }


def _get_pending_proposals() -> list[dict]:
    """Read pending proposals for heartbeat payload. Best-effort, never raises."""
    try:
        if not APPROVAL_PROPOSALS_LOG.exists():
            return []
        from core.agency.approval import ApprovalQueue
        queue = ApprovalQueue(APPROVAL_PROPOSALS_LOG)
        proposals = []
        for p in queue.list_pending():
            data = p.model_dump()
            data["tool_args"] = _redact_tool_args(data.get("tool_args", {}))
            proposals.append(data)
        return proposals
    except Exception:
        return []


def _build_heartbeat_payload() -> dict:
    from core.autonomic.daemon import get_status
    from core.autonomic.fsm import get_current_state

    return {
        "fsm_state": get_current_state().value,
        "daemon": get_status(),
        "pending_proposals": _get_pending_proposals(),
    }


@router.websocket("/ws/heartbeat")
async def heartbeat(ws: WebSocket, token: str | None = Query(None)):
    if not validate_ws_token(token):
        await ws.close(code=4001, reason="Unauthorized")
        return
    await ws.accept()
    try:
        while True:
            payload = _build_heartbeat_payload()
            await ws.send_text(json.dumps(payload))
            await asyncio.sleep(30)
    except WebSocketDisconnect:
        asyncio.get_event_loop().call_later(60, _try_close_session)
    except Exception:
        pass


def _try_close_session():
    """Attempt session close after WS disconnect grace period."""
    try:
        from core.memory.session import close_session
        close_session(reason="ws_disconnect")
    except Exception:
        pass
