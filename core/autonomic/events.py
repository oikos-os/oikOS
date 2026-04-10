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
from typing import Callable

from core.interface.config import PROJECT_ROOT

log = logging.getLogger(__name__)

EVENTS_LOG: Path = PROJECT_ROOT / "logs" / "events.jsonl"
MAX_EVENT_LINES = 5000


# ── Notification hook (set by notifications module; None during bootstrap) ──
# Assigned lazily on first call to avoid circular imports. The hook function
# takes the full event record dict and is called before the log write so
# notifications fire even if the write fails (disk full, permission errors, etc.).
_notification_hook: Callable[[dict], None] | None = None


def _dispatch_notification(record: dict) -> None:
    """Call the notification hook if set, swallowing all errors.

    On first call, lazy-imports notifications.get_manager() and caches a lambda
    in _notification_hook. If the import fails for any reason (ImportError,
    SyntaxError in the target module, transitive import failure, etc.), caches
    a no-op sentinel so subsequent calls skip the import machinery entirely.
    Call-time exceptions from the hook are also swallowed at debug level.
    """
    global _notification_hook
    if _notification_hook is None:
        # Lazy import to break circular dependency (notifications → events → notifications).
        # Catch Exception (not BaseException) so KeyboardInterrupt still propagates.
        try:
            from core.autonomic.notifications import get_manager
            _notification_hook = lambda r: get_manager().handle_event(r)
        except Exception as e:
            log.debug("Notification hook import failed: %s", e)
            _notification_hook = lambda r: None  # sticky no-op — don't retry
            return
    try:
        _notification_hook(record)
    except Exception as e:
        log.debug("Notification hook call failed: %s", e)


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
    """Append one event record to events.jsonl and dispatch notifications.

    The notification hook runs BEFORE the log write so notifications fire
    even if the write fails (disk full, permission error, etc.).
    """
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "category": category,
        "type": event_type,
        "data": data or {},
    }
    # Fire notifications first — independent of log write success
    _dispatch_notification(record)
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
