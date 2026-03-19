"""Agency endpoints — autonomy matrix proposals, approval queue."""

from __future__ import annotations

import json

from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel

from core.autonomic.events import emit_event

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


class RejectRequest(BaseModel):
    reason: str | None = None


# ── Endpoints ────────────────────────────────────────────────────────

@router.post("/propose", status_code=201)
def propose_action(req: ProposeRequest, queue=Depends(_get_queue)):
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
    )
    emit_event("agency", "proposal_created", {
        "proposal_id": prop.proposal_id,
        "action_type": req.action_type,
        "tool_name": req.tool_name,
    })
    return prop.model_dump()


@router.post("/approve/{proposal_id}")
def approve_action(proposal_id: str, queue=Depends(_get_queue)):
    try:
        prop = queue.approve(proposal_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Proposal {proposal_id!r} not found")
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    emit_event("agency", "proposal_approved", {"proposal_id": proposal_id})
    return prop.model_dump()


@router.post("/reject/{proposal_id}")
def reject_action(
    proposal_id: str,
    req: RejectRequest | None = Body(None),
    queue=Depends(_get_queue),
):
    reason = req.reason if req else None
    try:
        prop = queue.reject(proposal_id, reason=reason)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Proposal {proposal_id!r} not found")
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    emit_event("agency", "proposal_rejected", {
        "proposal_id": proposal_id,
        "rejection_reason": reason,
    })
    return prop.model_dump()


@router.get("/pending")
def list_pending(queue=Depends(_get_queue)):
    return [p.model_dump() for p in queue.list_pending()]
