"""Approval endpoints — list, review, approve, reject, dismiss pending actions."""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel

from core.autonomic.events import emit_event

log = logging.getLogger(__name__)

router = APIRouter()


# ── Dependency ───────────────────────────────────────────────────────

_queue_instance = None


def _get_queue():
    global _queue_instance
    if _queue_instance is None:
        from core.agency.approval import ApprovalQueue
        _queue_instance = ApprovalQueue()
    return _queue_instance


# ── Request models ───────────────────────────────────────────────────

class ProposeRequest(BaseModel):
    action_type: str
    tool_name: str
    tool_args: dict = {}
    reason: str
    estimated_tokens: int = 0
    risk_level: str = "low"
    room: str = ""


class RejectRequest(BaseModel):
    reason: str | None = None


# ── Response serialization ───────────────────────────────────────────

def _serialize(prop) -> dict:
    args = dict(prop.tool_args)
    if "content" in args:
        content = str(args.pop("content"))
        preview = content[:200] + "..." if len(content) > 200 else content
        args["content_preview"] = preview
    return {
        "id": prop.proposal_id,
        "tool_name": prop.tool_name,
        "action": prop.action,
        "risk_level": prop.risk_level,
        "requested_at": prop.created_at,
        "arguments": args,
        "room": prop.room,
        "expires_at": prop.expires_at,
        "status": prop.status,
    }


# ── Endpoints ────────────────────────────────────────────────────────

@router.get("")
def list_pending(queue=Depends(_get_queue)):
    """List all pending approval requests."""
    queue.expire_stale()
    return {"pending": [_serialize(p) for p in queue.list_pending()]}


@router.get("/{proposal_id}")
def get_approval(proposal_id: str, queue=Depends(_get_queue)):
    """Get details of a specific approval request."""
    queue.expire_stale()
    if proposal_id not in queue._proposals:
        raise HTTPException(status_code=404, detail=f"Proposal {proposal_id!r} not found")
    return _serialize(queue._proposals[proposal_id])


@router.post("/propose", status_code=201)
def propose_action(req: ProposeRequest, queue=Depends(_get_queue)):
    """Create a new approval request (used internally by autonomy middleware)."""
    serialized = json.dumps(req.tool_args, default=str)
    if len(serialized.encode()) > 4096:
        raise HTTPException(status_code=413, detail="tool_args exceeds 4096-byte limit")

    from pathlib import Path

    from core.agency.autonomy import AutonomyMatrix
    from core.interface.models import ActionClass

    matrix = AutonomyMatrix(Path("autonomy_matrix.json"))
    classification = matrix.classify(req.action_type)
    if classification == ActionClass.PROHIBITED:
        raise HTTPException(status_code=403, detail=f"Action type {req.action_type!r} is PROHIBITED")

    prop = queue.propose(
        action_type=req.action_type,
        tool_name=req.tool_name,
        tool_args=req.tool_args,
        reason=req.reason,
        estimated_tokens=req.estimated_tokens,
        risk_level="low" if classification == ActionClass.SAFE else "medium",
        room=req.room,
    )
    emit_event("agency", "proposal_created", {
        "proposal_id": prop.proposal_id,
        "action_type": req.action_type,
        "tool_name": req.tool_name,
    })
    return _serialize(prop)


@router.post("/{proposal_id}/approve")
def approve_action(proposal_id: str, queue=Depends(_get_queue)):
    """Approve a pending action — tool executes on next retry."""
    try:
        prop = queue.approve(proposal_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Proposal {proposal_id!r} not found")
    except ValueError as e:
        log.warning("[approve_action] conflict: %s", e)
        raise HTTPException(status_code=409, detail="Proposal already resolved")
    emit_event("agency", "proposal_approved", {"proposal_id": proposal_id})
    return _serialize(prop)


@router.post("/{proposal_id}/reject")
def reject_action(
    proposal_id: str,
    req: RejectRequest | None = Body(None),
    queue=Depends(_get_queue),
):
    """Reject a pending action — returns rejection message to LLM."""
    reason = req.reason if req else None
    try:
        prop = queue.reject(proposal_id, reason=reason)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Proposal {proposal_id!r} not found")
    except ValueError as e:
        log.warning("[reject_action] conflict: %s", e)
        raise HTTPException(status_code=409, detail="Proposal already resolved")
    emit_event("agency", "proposal_rejected", {
        "proposal_id": proposal_id,
        "rejection_reason": reason,
    })
    return _serialize(prop)


@router.delete("/{proposal_id}")
def dismiss_action(proposal_id: str, queue=Depends(_get_queue)):
    """Dismiss without action — expires the request."""
    try:
        prop = queue.reject(proposal_id, reason="dismissed")
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Proposal {proposal_id!r} not found")
    except ValueError as e:
        log.warning("[dismiss_action] conflict: %s", e)
        raise HTTPException(status_code=409, detail="Proposal already resolved")
    emit_event("agency", "proposal_dismissed", {"proposal_id": proposal_id})
    return _serialize(prop)
