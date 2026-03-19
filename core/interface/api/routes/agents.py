"""Agent endpoints — consolidation, eval, gauntlet, jobs."""

from __future__ import annotations

import json
import uuid
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel

router = APIRouter()

# ── In-memory job tracker ────────────────────────────────────────────
_jobs: dict[str, dict] = {}


class ReviewRequest(BaseModel):
    proposal_id: str
    status: str  # "approved" | "rejected"
    apply: bool = False


# ── Consolidation ────────────────────────────────────────────────────

@router.get("/consolidation/proposals")
def consolidation_proposals():
    from core.agency.consolidation import load_pending_proposals

    proposals = load_pending_proposals()
    return [p.model_dump() for p in proposals]


@router.post("/consolidation/review")
def consolidation_review(req: ReviewRequest):
    from core.agency.consolidation import mark_proposal_status

    mark_proposal_status(req.proposal_id, req.status, apply=req.apply)
    return {"status": req.status, "proposal_id": req.proposal_id}


# ── Eval ─────────────────────────────────────────────────────────────

@router.get("/eval/latest")
def eval_latest():
    from core.interface.config import EVAL_SUMMARY_LOG

    return _read_last_jsonl_line(EVAL_SUMMARY_LOG)


# ── Gauntlet ─────────────────────────────────────────────────────────

@router.get("/gauntlet/latest")
def gauntlet_latest():
    from core.interface.config import GAUNTLET_HISTORY_LOG

    return _read_last_jsonl_line(GAUNTLET_HISTORY_LOG)


@router.post("/gauntlet/run")
def gauntlet_run(background_tasks: BackgroundTasks):
    job_id = uuid.uuid4().hex[:12]
    _jobs[job_id] = {"status": "running", "result": None, "error": None}
    background_tasks.add_task(_run_gauntlet_job, job_id)
    return {"job_id": job_id, "status": "running"}


@router.get("/jobs/{job_id}")
def get_job(job_id: str):
    if job_id not in _jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    return _jobs[job_id]


# ── Helpers ──────────────────────────────────────────────────────────

def _read_last_jsonl_line(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        lines = path.read_text(encoding="utf-8").strip().split("\n")
        return json.loads(lines[-1]) if lines and lines[-1] else {}
    except (json.JSONDecodeError, OSError):
        return {}


def _run_gauntlet_job(job_id: str) -> None:
    try:
        from core.agency.adversarial import run_gauntlet

        summary = run_gauntlet()
        _jobs[job_id] = {
            "status": "completed",
            "result": {
                "total": summary.total,
                "passed": summary.passed,
                "soft_fails": summary.soft_fails,
                "hard_fails": summary.hard_fails,
                "regressions": summary.regressions,
            },
            "error": None,
        }
    except Exception as e:
        _jobs[job_id] = {"status": "failed", "result": None, "error": str(e)}
