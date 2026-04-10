"""Agent endpoints — consolidation, eval, gauntlet, jobs."""

from __future__ import annotations

import json
import logging
import time
import uuid
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel

log = logging.getLogger(__name__)
router = APIRouter()

# ── In-memory job tracker (bounded) ──────────────────────────────────
_MAX_JOBS = 100
_JOB_TTL_SECONDS = 3600  # 1 hour
_jobs: dict[str, dict] = {}


def _evict_stale_jobs() -> None:
    now = time.time()
    expired = [k for k, v in _jobs.items() if now - v.get("created", 0) > _JOB_TTL_SECONDS]
    for k in expired:
        del _jobs[k]
    # If still over limit, drop oldest
    while len(_jobs) > _MAX_JOBS:
        oldest = min(_jobs, key=lambda k: _jobs[k].get("created", 0))
        del _jobs[oldest]


class ReviewRequest(BaseModel):
    proposal_id: str
    status: str  # "approved" | "rejected"
    apply: bool = False


# ── Tools ────────────────────────────────────────────────────────────

@router.get("/tools")
def list_tools():
    """Return registered MCP tools grouped by toolset."""
    try:
        import core.framework.tools  # noqa: F401 — triggers @oikos_tool registration
        from core.framework.decorator import get_registered_tools

        registry = get_registered_tools()
        toolsets: dict[str, list[str]] = {}
        for name, (_, meta) in registry.items():
            ts = getattr(meta, "toolset", None) or "other"
            toolsets.setdefault(ts, []).append(name)
        total = sum(len(v) for v in toolsets.values())
        return {"total": total, "toolsets": {k: sorted(v) for k, v in sorted(toolsets.items())}}
    except Exception:
        return {"total": 0, "toolsets": {}}


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
    _evict_stale_jobs()
    job_id = uuid.uuid4().hex[:12]
    _jobs[job_id] = {"status": "running", "result": None, "error": None, "created": time.time()}
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
    except Exception as exc:
        log.error("Gauntlet job %s failed: %s: %s", job_id, type(exc).__name__, exc)
        _jobs[job_id] = {"status": "failed", "result": None, "error": "Gauntlet execution failed"}
