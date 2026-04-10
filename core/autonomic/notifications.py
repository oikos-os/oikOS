"""T-119: Background notification manager with three-tier policy.

Hooks into core/autonomic/events.py::emit_event() as the single choke point.
Every emitter in the codebase automatically triggers notification evaluation —
no per-emitter wiring required.

Tiers:
  - MUST:   every occurrence surfaced (safety, budget, session warnings)
  - SHOULD: first per session, optional escalation (idle cascade, restarts)
  - SILENT: event bus only, never surfaced (housekeeping, per-query spam)

Surfaces:
  - TUI:  ring buffer consumed via GET /api/notifications/pending (T-102 pattern)
  - Web:  SSE on existing /api/events stream
  - Desktop: BurntToast PowerShell subprocess for CRITICAL severity only
"""
from __future__ import annotations

import logging
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Optional

log = logging.getLogger(__name__)


class NotificationTier(Enum):
    """Three-tier notification policy."""
    MUST = "must"       # Every occurrence → user sees it
    SHOULD = "should"   # First per session → user sees it; subsequent → suppressed
    SILENT = "silent"   # Never surfaced — event bus + logs only


class NotificationSeverity(Enum):
    """Maps to Textual severity levels + desktop escalation."""
    INFO = "information"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"  # Triggers desktop BurntToast in addition to TUI/web


@dataclass
class NotificationRule:
    """Policy for a single event type."""
    event_key: str                                      # Composite: f"{category}.{type}"
    tier: NotificationTier
    severity: NotificationSeverity
    dedup_key: str                                      # Session-scoped dedup identifier
    message_template: str                               # Human-readable with {field} interpolation
    title: Optional[str] = None                         # Toast title (None = use event_key)
    escalation_threshold: int = 0                       # 0 = no escalation
    escalation_severity: Optional[NotificationSeverity] = None
    escalation_message: Optional[str] = None            # Template override when escalated
    timeout_seconds: int = 5                            # Toast display duration


@dataclass
class NotificationState:
    """Per-session tracking for dedup and escalation."""
    fired_keys: dict[str, int] = field(default_factory=dict)
    session_start: float = field(default_factory=time.time)

    def should_fire(self, rule: NotificationRule) -> bool:
        """Apply tier policy with dedup and escalation."""
        if rule.tier == NotificationTier.SILENT:
            return False
        count = self.fired_keys.get(rule.dedup_key, 0)
        if rule.tier == NotificationTier.MUST:
            return True
        # SHOULD tier: first per session, unless escalation threshold hit
        if count == 0:
            return True
        if rule.escalation_threshold > 0 and count >= rule.escalation_threshold:
            return True
        return False

    def record(self, rule: NotificationRule) -> None:
        """Record that a notification was evaluated (fired or suppressed)."""
        self.fired_keys[rule.dedup_key] = self.fired_keys.get(rule.dedup_key, 0) + 1

    def reset(self) -> None:
        """Clear session state (called on new session start)."""
        self.fired_keys.clear()
        self.session_start = time.time()


@dataclass
class PendingNotification:
    """A notification waiting to be consumed by TUI/web surfaces."""
    timestamp: float
    message: str
    title: str
    severity: str                                       # Textual severity string
    timeout_seconds: int
    event_key: str

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "message": self.message,
            "title": self.title,
            "severity": self.severity,
            "timeout_seconds": self.timeout_seconds,
            "event_key": self.event_key,
        }


def _build_default_rules() -> dict[str, NotificationRule]:
    """Construct the default notification policy table."""
    rules: list[NotificationRule] = [
        # ── MUST tier ─────────────────────────────────────────────
        NotificationRule(
            event_key="safety.pii_anonymized",
            tier=NotificationTier.MUST,
            severity=NotificationSeverity.INFO,
            dedup_key="pii_scrub",
            message_template="PII anonymized ({entity_count} entities)",
            title="PII Scrubbed",
            timeout_seconds=4,
        ),
        NotificationRule(
            event_key="safety.output_filter_activated",
            tier=NotificationTier.MUST,
            severity=NotificationSeverity.WARNING,
            dedup_key="output_filter",
            message_template="Output filtered — {level} sensitivity detected",
            title="Output Filter",
            timeout_seconds=5,
        ),
        NotificationRule(
            event_key="safety.never_leave_activated",
            tier=NotificationTier.MUST,
            severity=NotificationSeverity.WARNING,
            dedup_key="never_leave",
            message_template="Kept local — NEVER_LEAVE active",
            title="NEVER_LEAVE",
            timeout_seconds=5,
        ),
        NotificationRule(
            event_key="daemon.budget_critical",
            tier=NotificationTier.MUST,
            severity=NotificationSeverity.CRITICAL,
            dedup_key="budget_critical",
            message_template="Monthly budget at {usage_percent}% — cloud queries limited",
            title="Budget Critical",
            timeout_seconds=10,
        ),
        NotificationRule(
            event_key="daemon.session_warning",
            tier=NotificationTier.MUST,
            severity=NotificationSeverity.WARNING,
            dedup_key="session_warning",
            message_template="Session closing in {minutes_remaining} minutes (inactivity)",
            title="Session Closing",
            timeout_seconds=10,
        ),

        # ── SHOULD tier ───────────────────────────────────────────
        NotificationRule(
            event_key="fsm.idle_cascade",
            tier=NotificationTier.SHOULD,
            severity=NotificationSeverity.INFO,
            dedup_key="idle_cascade",
            message_template="IDLE — vault reindex + consolidation running",
            title="IDLE Cascade",
            timeout_seconds=4,
        ),
        NotificationRule(
            event_key="inference.restart_attempt",
            tier=NotificationTier.SHOULD,
            severity=NotificationSeverity.WARNING,
            dedup_key="restart_attempt",
            message_template="Local inference restart {attempt}/3",
            title="Inference Restart",
            escalation_threshold=2,
            escalation_severity=NotificationSeverity.ERROR,
            escalation_message="Local inference exhausted — cloud fallback active",
            timeout_seconds=10,
        ),
        NotificationRule(
            event_key="daemon.budget_warning",
            tier=NotificationTier.SHOULD,
            severity=NotificationSeverity.INFO,
            dedup_key="budget_warning",
            message_template="Cloud budget at {usage_percent}%",
            title="Budget Warning",
            timeout_seconds=6,
        ),

        # ── SILENT tier (explicitly listed for clarity) ───────────
        NotificationRule(
            event_key="daemon.vault_reindex",
            tier=NotificationTier.SILENT,
            severity=NotificationSeverity.INFO,
            dedup_key="vault_reindex",
            message_template="",
        ),
        NotificationRule(
            event_key="daemon.log_rotation",
            tier=NotificationTier.SILENT,
            severity=NotificationSeverity.INFO,
            dedup_key="log_rotation",
            message_template="",
        ),
        NotificationRule(
            event_key="daemon.prewarm",
            tier=NotificationTier.SILENT,
            severity=NotificationSeverity.INFO,
            dedup_key="prewarm",
            message_template="",
        ),
        NotificationRule(
            event_key="daemon.session_auto_close",
            tier=NotificationTier.SILENT,
            severity=NotificationSeverity.INFO,
            dedup_key="session_auto_close",
            message_template="",
        ),
        NotificationRule(
            event_key="daemon.restart_exhausted",
            tier=NotificationTier.SILENT,
            severity=NotificationSeverity.INFO,
            dedup_key="restart_exhausted",
            message_template="",
        ),
    ]
    return {r.event_key: r for r in rules}


class NotificationManager:
    """Subscribes to event bus, applies policy, routes to surfaces.

    Single instance per process. Thread-safe — state mutations are locked.
    """

    def __init__(self, max_pending: int = 50):
        self.state = NotificationState()
        self.rules: dict[str, NotificationRule] = _build_default_rules()
        self._pending: deque[PendingNotification] = deque(maxlen=max_pending)
        self._lock = threading.Lock()
        # Dispatch function — default is internal buffer; can be overridden for tests.
        # Signature: (message, title, severity, timeout_seconds, event_key)
        self._dispatch_fn: Callable[[str, str, NotificationSeverity, int, str], None] = self._default_dispatch

    def _notifications_enabled_for_tier(self, tier: NotificationTier | None) -> bool:
        """Check master + tier-specific setting. Called on every event.

        Returns False if the master `notifications` setting is off (all tiers
        suppressed) or if the specific tier is disabled. Returns True by default
        if settings cannot be loaded (bootstrap / test context).
        """
        try:
            from core.interface.settings import get_setting
        except ImportError:
            return True  # Bootstrap / test context — allow

        # Master switch — suppresses all tiers when False
        try:
            master = get_setting("notifications")
        except (KeyError, Exception):
            master = True
        if not master:
            return False

        if tier is None:
            return True  # Only master check requested

        # Tier-specific switches
        if tier == NotificationTier.MUST:
            try:
                return bool(get_setting("notifications_must_enabled"))
            except (KeyError, Exception):
                return True
        if tier == NotificationTier.SHOULD:
            try:
                return bool(get_setting("notifications_should_enabled"))
            except (KeyError, Exception):
                return True
        return True  # SILENT never reaches here anyway

    def handle_event(self, event: dict) -> None:
        """Called from emit_event() for every event on the bus.

        State mutations (should_fire + record) run under the lock.
        Message resolution and dispatch run outside the lock so that slow
        I/O in _dispatch_fn (e.g., Task 9 BurntToast subprocess) does not
        block concurrent event handling or drain_pending calls.
        """
        # Fast path: master notifications switch
        if not self._notifications_enabled_for_tier(None):
            return

        category = event.get("category", "")
        event_type = event.get("type", "")
        composite_key = f"{category}.{event_type}"

        rule = self.rules.get(composite_key)
        if rule is None:
            return  # Unknown event — implicitly silent

        # Tier-specific switch
        if not self._notifications_enabled_for_tier(rule.tier):
            return

        # ── Critical section: state mutation only ──
        with self._lock:
            should_fire = self.state.should_fire(rule)
            self.state.record(rule)
            if not should_fire:
                return
            count = self.state.fired_keys.get(rule.dedup_key, 0)

        # ── Outside lock: pure computation + dispatch ──
        is_escalated = (
            rule.escalation_threshold > 0
            and count >= rule.escalation_threshold
            and rule.tier == NotificationTier.SHOULD
        )

        data = event.get("data", {})
        if is_escalated and rule.escalation_message:
            message = self._safe_format(rule.escalation_message, data)
        else:
            message = self._safe_format(rule.message_template, data)

        if is_escalated and rule.escalation_severity:
            severity = rule.escalation_severity
        else:
            severity = rule.severity

        title = rule.title or composite_key

        try:
            self._dispatch_fn(message, title, severity, rule.timeout_seconds, composite_key)
        except Exception as e:
            log.warning("Notification dispatch failed: %s", e)

    @staticmethod
    def _safe_format(template: str, data: dict) -> str:
        """Interpolate template with data, falling back to template on any format error."""
        try:
            return template.format(**data)
        except (KeyError, IndexError, ValueError, TypeError, AttributeError):
            return template

    def _default_dispatch(self, message: str, title: str, severity: NotificationSeverity,
                         timeout: int, event_key: str) -> None:
        """Append to pending buffer for TUI/API consumption.

        Critical-severity notifications also trigger a desktop toast via
        BurntToast, gated by the notifications_desktop_enabled setting.
        """
        pending = PendingNotification(
            timestamp=time.time(),
            message=message,
            title=title,
            severity=severity.value,
            timeout_seconds=timeout,
            event_key=event_key,
        )
        self._pending.append(pending)
        # CRITICAL severity escalates to desktop (gated by settings, non-blocking)
        if severity == NotificationSeverity.CRITICAL and self._desktop_enabled():
            _show_desktop_notification(title, message)

    @staticmethod
    def _desktop_enabled() -> bool:
        """Check notifications_desktop_enabled setting. Defaults True on failure."""
        try:
            from core.interface.settings import get_setting
            return bool(get_setting("notifications_desktop_enabled"))
        except Exception:
            return True  # Bootstrap / test context — allow

    def drain_pending(self, since_timestamp: float | None = None) -> list[dict]:
        """Return pending notifications newer than timestamp. Non-destructive read."""
        with self._lock:
            items = list(self._pending)
        if since_timestamp is not None:
            items = [n for n in items if n.timestamp > since_timestamp]
        return [n.to_dict() for n in items]

    def reset_session(self) -> None:
        """Clear session state (called on new session)."""
        with self._lock:
            self.state.reset()
            self._pending.clear()


def _show_desktop_notification(title: str, message: str) -> None:
    """Fire-and-forget BurntToast desktop notification (Windows only).

    Non-blocking — spawns PowerShell in a detached subprocess so slow BurntToast
    initialization does not delay notification dispatch. Uses CREATE_NO_WINDOW
    on Windows to suppress the console flash. Failures (BurntToast not installed,
    PowerShell missing) are caught and logged at debug level.
    """
    import subprocess
    import sys

    if sys.platform != "win32":
        log.debug("Desktop notification skipped (non-Windows): %s", title)
        return

    # Escape single quotes for PowerShell string literals
    safe_title = title.replace("'", "''")
    safe_message = message.replace("'", "''")
    ps_script = (
        f"Import-Module BurntToast -ErrorAction SilentlyContinue; "
        f"New-BurntToastNotification -Text '{safe_title}', '{safe_message}'"
    )
    try:
        subprocess.Popen(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_script],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, FileNotFoundError) as e:
        log.debug("BurntToast invocation failed: %s", e)


# Module-level singleton (lazy-initialized)
_manager: NotificationManager | None = None
_manager_lock = threading.Lock()


def get_manager() -> NotificationManager:
    """Get or create the process-wide NotificationManager."""
    global _manager
    if _manager is None:
        with _manager_lock:
            if _manager is None:
                _manager = NotificationManager()
    return _manager


def reset_manager() -> None:
    """Reset the process-wide manager singleton (test-only).

    Clears the cached instance so the next get_manager() call creates a fresh
    NotificationManager. Used by test fixtures to isolate state between tests.
    """
    global _manager
    with _manager_lock:
        _manager = None
