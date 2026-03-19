"""Event bus — append-only JSONL log for system activity.

Categories:
    fsm         — state transitions (ACTIVE→IDLE, etc.)
    inference   — query start/complete, route decisions
    agent       — gauntlet, eval, consolidation runs
    cloud       — cloud dispatch, health check results
    error       — system errors, fallbacks
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from core.interface.config import PROJECT_ROOT

log = logging.getLogger(__name__)

EVENTS_LOG: Path = PROJECT_ROOT / "logs" / "events.jsonl"
MAX_EVENT_LINES = 5000


def _rotate_if_needed() -> None:
    """Keep only the last MAX_EVENT_LINES entries."""
    try:
        if not EVENTS_LOG.exists():
            return
        lines = EVENTS_LOG.read_text(encoding="utf-8").strip().split("\n")
        if len(lines) > MAX_EVENT_LINES:
            EVENTS_LOG.write_text(
                "\n".join(lines[-MAX_EVENT_LINES:]) + "\n", encoding="utf-8"
            )
    except OSError as e:
        log.warning("Event log rotation failed: %s", e)


def emit_event(category: str, event_type: str, data: dict | None = None) -> None:
    """Append one event record to events.jsonl."""
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "category": category,
        "type": event_type,
        "data": data or {},
    }
    try:
        EVENTS_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(EVENTS_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
        _rotate_if_needed()
    except OSError as e:
        log.warning("Event bus write failed: %s", e)


def read_events(since: str | None = None, limit: int = 50) -> list[dict]:
    """Read recent events, optionally filtered by timestamp."""
    if not EVENTS_LOG.exists():
        return []

    events: list[dict] = []
    try:
        for line in EVENTS_LOG.read_text(encoding="utf-8").strip().split("\n"):
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
                if since and entry.get("timestamp", "") <= since:
                    continue
                events.append(entry)
            except json.JSONDecodeError:
                continue
    except OSError:
        return []

    return events[-limit:]
