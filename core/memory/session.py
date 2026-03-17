"""Session boundary management — UUID4 session IDs with deterministic expiry.

Session log layout (per session):
    logs/sessions/YYYY-MM-DD/
        SESSION-{id}.jsonl          # Per-interaction records (query + response pairs)
        SESSION-{id}_summary.json   # Auto-generated at session close

Each JSONL entry is one of two types:
    type="query"    — logged at query receipt (step 0)
    type="response" — logged after inference completes (step N), keyed by query_hash
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from core.interface.config import LOGS_DIR

if TYPE_CHECKING:
    from core.interface.models import InferenceResponse

log = logging.getLogger(__name__)

SESSIONS_DIR = LOGS_DIR  # LOGS_DIR is already logs/sessions per config.py
SESSION_STATE_FILE = LOGS_DIR / ".current_session.json"
SESSION_TIMEOUT_MINUTES = 30


# ── Internal helpers ───────────────────────────────────────────────────────────

def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _session_dir(date_str: str) -> Path:
    """Return the date-based subdirectory for a session's logs."""
    d = SESSIONS_DIR / date_str
    d.mkdir(parents=True, exist_ok=True)
    return d


def _session_log_path(session_id: str, started_at: str) -> Path:
    """Return path to the JSONL interaction log for a session."""
    date_str = datetime.fromisoformat(started_at).strftime("%Y-%m-%d")
    return _session_dir(date_str) / f"SESSION-{session_id}.jsonl"


def _session_summary_path(session_id: str, started_at: str) -> Path:
    """Return path to the JSON summary file for a session."""
    date_str = datetime.fromisoformat(started_at).strftime("%Y-%m-%d")
    return _session_dir(date_str) / f"SESSION-{session_id}_summary.json"


def _load_state() -> dict | None:
    """Load persisted session state, or None if missing/corrupt."""
    if not SESSION_STATE_FILE.exists():
        return None
    try:
        return json.loads(SESSION_STATE_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        log.warning("Corrupt session state file, will create new session.")
        return None


def _save_state(state: dict) -> None:
    SESSION_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    SESSION_STATE_FILE.write_text(
        json.dumps(state, indent=2), encoding="utf-8"
    )


def _is_expired(state: dict) -> bool:
    """Check all three deterministic expiry signals."""
    now = _utcnow()

    # Signal (c): new calendar day (UTC)
    started = datetime.fromisoformat(state["started_at"])
    if now.date() != started.date():
        return True

    # Signal (b): inactivity timeout
    last_active = datetime.fromisoformat(state["last_active_at"])
    elapsed_minutes = (now - last_active).total_seconds() / 60
    if elapsed_minutes > state.get("timeout_minutes", SESSION_TIMEOUT_MINUTES):
        return True

    # Signal (a): explicit close is handled by close_session()
    return False


def _append_to_log(session_id: str, started_at: str, entry: dict) -> None:
    """Append one JSON record to the session's JSONL file."""
    log_path = _session_log_path(session_id, started_at)
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def _generate_summary(state: dict) -> dict:
    """Build aggregated summary from a session's JSONL log."""
    log_path = _session_log_path(state["session_id"], state["started_at"])

    summary: dict = {
        "session_id": state["session_id"],
        "started_at": state["started_at"],
        "closed_at": state.get("closed_at", _utcnow().isoformat()),
        "close_reason": state.get("close_reason", "unknown"),
        "interaction_count": state.get("interaction_count", 0),
        "duration_minutes": None,
        "routes": {"local": 0, "cloud": 0, "unknown": 0},
        "total_credits_used": 0,
        "total_tokens": 0,
        "pii_events": 0,
        "adversarial_events": 0,
        "avg_confidence": None,
        "confidence_scores": [],
    }

    # Compute duration
    try:
        start = datetime.fromisoformat(state["started_at"])
        end = datetime.fromisoformat(summary["closed_at"])
        summary["duration_minutes"] = round((end - start).total_seconds() / 60, 1)
    except Exception:
        pass

    # Parse JSONL for query/response records
    first_query_found = False
    if log_path.exists():
        try:
            with open(log_path, encoding="utf-8") as f:
                for line in f:
                    entry = json.loads(line.strip())
                    if not first_query_found and entry.get("type") == "query":
                        summary["first_query"] = (entry.get("query") or "")[:100]
                        first_query_found = True
                    if entry.get("type") != "response":
                        continue
                    route = entry.get("route", "unknown")
                    summary["routes"][route] = summary["routes"].get(route, 0) + 1
                    summary["total_credits_used"] += entry.get("credits_used", 0)
                    summary["total_tokens"] += entry.get("tokens_used", 0)
                    if entry.get("pii_detected"):
                        summary["pii_events"] += 1
                    if entry.get("adversarial_detected"):
                        summary["adversarial_events"] += 1
                    conf = entry.get("confidence")
                    if conf is not None:
                        summary["confidence_scores"].append(conf)
        except Exception as e:
            log.warning("Could not parse session log for summary: %s", e)

    # Compute avg confidence
    if summary["confidence_scores"]:
        summary["avg_confidence"] = round(
            sum(summary["confidence_scores"]) / len(summary["confidence_scores"]), 2
        )
    del summary["confidence_scores"]  # Don't persist the raw list

    return summary


# ── Public API ─────────────────────────────────────────────────────────────────

def get_or_create_session() -> dict:
    """Return the active session state, creating a new one if expired or absent."""
    state = _load_state()

    if state is not None and not _is_expired(state):
        state["last_active_at"] = _utcnow().isoformat()
        state["interaction_count"] = state.get("interaction_count", 0) + 1
        _save_state(state)
        return state

    now = _utcnow()
    state = {
        "session_id": uuid.uuid4().hex[:16],
        "started_at": now.isoformat(),
        "last_active_at": now.isoformat(),
        "timeout_minutes": SESSION_TIMEOUT_MINUTES,
        "interaction_count": 1,
    }
    _save_state(state)
    log.info("New session started: %s", state["session_id"])
    return state


def close_session(reason: str = "explicit") -> dict | None:
    """Explicitly close the current session. Returns the closed state or None."""
    state = _load_state()
    if state is None:
        return None

    state["closed_at"] = _utcnow().isoformat()
    state["close_reason"] = reason

    _archive_session(state)

    try:
        SESSION_STATE_FILE.unlink()
    except OSError:
        pass

    log.info("Session closed: %s", state["session_id"])
    return state


def _archive_session(state: dict) -> None:
    """Write closed session summary JSON to the session's date folder."""
    summary = _generate_summary(state)
    summary_path = _session_summary_path(state["session_id"], state["started_at"])
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    log.info("Session summary written: %s", summary_path)


def log_interaction(
    session_id: str,
    session_started_at: str,
    query_hash: str,
    query: str,
    source: str = "handler",
) -> None:
    """Log query receipt (step 0 — before routing/inference).

    Args:
        session_id: Active session ID.
        session_started_at: ISO timestamp of session start (for path resolution).
        query_hash: SHA256[:16] of the query.
        query: Raw query text.
        source: "handler" or "stream" — which execution path called this.
    """
    entry = {
        "type": "query",
        "timestamp": _utcnow().isoformat(),
        "session_id": session_id,
        "query_hash": query_hash,
        "query": query,
        "source": source,
    }
    _append_to_log(session_id, session_started_at, entry)


def log_interaction_complete(
    session_id: str,
    session_started_at: str,
    query_hash: str,
    response: "InferenceResponse",
) -> None:
    """Log inference outcome (after routing/inference completes).

    Called at the end of execute_query() and execute_query_stream() with the
    final InferenceResponse. Captures full routing decision, model, confidence,
    PII state, credit cost, and a response preview.

    Args:
        session_id: Active session ID.
        session_started_at: ISO timestamp of session start (for path resolution).
        query_hash: SHA256[:16] — links back to the paired "query" record.
        response: Completed InferenceResponse from handler.
    """
    routing = response.routing_decision

    entry: dict = {
        "type": "response",
        "timestamp": _utcnow().isoformat(),
        "session_id": session_id,
        "query_hash": query_hash,
        "route": response.route.value if response.route else "unknown",
        "model_used": response.model_used,
        "confidence": response.confidence,
        "pii_detected": routing.pii_detected if routing else False,
        "pii_scrubbed": response.pii_scrubbed,
        "credits_used": response.credits_used,
        "cosine_gate_fired": routing.cosine_gate_fired if routing else False,
        "route_reason": routing.reason if routing else None,
        "tokens_used": 0,  # populated from eval_count if available
        "response_length_chars": len(response.text),
        "response_text": response.text[:10_000] if response.text else "",
        "adversarial_detected": False,  # overridden if adversarial result passed
        "contradiction_detected": (
            response.contradiction.has_contradiction
            if response.contradiction else False
        ),
    }

    _append_to_log(session_id, session_started_at, entry)


# ── API helpers ───────────────────────────────────────────────────────────────

def _find_session_jsonl(session_id: str) -> Path | None:
    """Find the JSONL log for a session across all date directories."""
    if not SESSIONS_DIR.exists():
        return None
    for d in SESSIONS_DIR.iterdir():
        if not d.is_dir() or d.name.startswith("."):
            continue
        candidate = d / f"SESSION-{session_id}.jsonl"
        if candidate.exists():
            return candidate
    return None


def _backfill_first_query(summary: dict) -> dict:
    """If summary lacks first_query, extract it from the JSONL."""
    if summary.get("first_query"):
        return summary
    log_file = _find_session_jsonl(summary["session_id"])
    if not log_file:
        return summary
    try:
        with open(log_file, encoding="utf-8") as f:
            for line in f:
                entry = json.loads(line.strip())
                if entry.get("type") == "query" and entry.get("query"):
                    summary["first_query"] = entry["query"][:100]
                    return summary
    except (json.JSONDecodeError, OSError):
        pass
    return summary


def list_recent_sessions(limit: int = 20) -> list[dict]:
    """Return recent session summaries sorted newest-first.

    Combines summary JSONs and orphan JSONL logs (sessions that were
    never formally closed). Deduplicates by session_id.
    """
    seen: set[str] = set()
    summaries: list[dict] = []
    if not SESSIONS_DIR.exists():
        return summaries

    date_dirs = sorted(SESSIONS_DIR.iterdir(), reverse=True)
    for d in date_dirs:
        if not d.is_dir() or d.name.startswith("."):
            continue

        # Collect from summary JSONs
        for f in sorted(d.glob("SESSION-*_summary.json"), reverse=True):
            try:
                s = json.loads(f.read_text(encoding="utf-8"))
                s = _backfill_first_query(s)
                routes = s.get("routes", {})
                has_inference = sum(routes.get(k, 0) for k in ("local", "cloud")) > 0
                if not s.get("first_query") and not has_inference:
                    continue
                if s["session_id"] not in seen:
                    seen.add(s["session_id"])
                    summaries.append(s)
            except (json.JSONDecodeError, OSError):
                continue

        # Collect from orphan JSONLs (no summary)
        for f in sorted(d.glob("SESSION-*.jsonl"), reverse=True):
            sid = f.stem.replace("SESSION-", "")
            if sid in seen:
                continue
            summary_file = d / f"SESSION-{sid}_summary.json"
            if summary_file.exists():
                continue
            try:
                first_query = None
                started_at = None
                count = 0
                with open(f, encoding="utf-8") as fh:
                    for line in fh:
                        entry = json.loads(line.strip())
                        if entry.get("type") == "query":
                            count += 1
                            if not first_query:
                                first_query = (entry.get("query") or "")[:100]
                                started_at = entry.get("timestamp")
                if first_query and count > 0:
                    seen.add(sid)
                    summaries.append({
                        "session_id": sid,
                        "started_at": started_at or "",
                        "interaction_count": count,
                        "first_query": first_query,
                    })
            except (json.JSONDecodeError, OSError):
                continue

    # Sort all by started_at descending
    summaries.sort(key=lambda s: s.get("started_at", ""), reverse=True)
    return summaries[:limit]


def load_session_transcript(session_id: str) -> list[dict]:
    """Load all JSONL entries for a given session ID."""
    if not SESSIONS_DIR.exists():
        return []

    for d in SESSIONS_DIR.iterdir():
        if not d.is_dir() or d.name.startswith("."):
            continue
        log_file = d / f"SESSION-{session_id}.jsonl"
        if log_file.exists():
            entries = []
            try:
                for line in log_file.read_text(encoding="utf-8").strip().split("\n"):
                    if line.strip():
                        entries.append(json.loads(line))
            except (json.JSONDecodeError, OSError):
                pass
            return entries

    return []
