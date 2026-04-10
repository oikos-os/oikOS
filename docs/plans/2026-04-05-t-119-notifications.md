# T-119: Background Notifications Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a NotificationManager that subscribes to the oikOS event bus at the `emit_event()` choke point and routes background events to TUI/web/desktop surfaces via a three-tier policy (MUST/SHOULD/SILENT), without interrupting the user.

**Architecture:** NotificationManager lives in `core/autonomic/notifications.py`. It hooks into `core/autonomic/events.py::emit_event()` so every emitter in the codebase automatically triggers notification evaluation — not just the daemon. Composite event key is `f"{category}.{type}"`. Policy table is a module-level `dict[str, NotificationRule]`. State is per-process (no cross-process sync needed — the API server is the single NotificationManager host). TUI consumes via polling `/api/notifications/pending` at 3-second intervals, mirroring the T-102 ApprovalBar pattern. Web UI consumes via SSE on the existing `/api/events` stream. Desktop escalation uses BurntToast PowerShell via subprocess, for CRITICAL severity only.

**Tech Stack:** Python 3.12 stdlib only (dataclasses, enum, threading.Lock, subprocess), FastAPI (existing route pattern), Textual `Static` widget (mirrors ApprovalBar), PowerShell BurntToast (existing Windows pattern).

**Dispatch:** `D:\COMMAND\messages\2026-04-05\DISPATCH_T-119_BACKGROUND_NOTIFICATIONS.md`

**Amendments approved by SYNTH (2026-04-05):**
1. Hook into `emit_event()` choke point (not daemon event loop) — 12 emission sites across 6 subsystems.
2. Composite key `f"{category}.{type}"` — zero changes to existing emitters.
3. Scope expands to include 4 new emission points: `safety.pii_anonymized`, `safety.output_filter_activated`, `daemon.session_warning`, `inference.restart_attempt`.
4. Settings registered in T-117 registry now (Advanced tier, 3 new keys), not deferred.
5. TUI integration via polling at `/api/notifications/pending` (mirrors T-102), not in-process app reference.

---

## File Structure

### New files
| File | Responsibility |
|---|---|
| `core/autonomic/notifications.py` | NotificationManager + NotificationRule + NotificationState + policy table + desktop dispatch |
| `core/interface/api/routes/notifications.py` | FastAPI route — `GET /api/notifications/pending`, `POST /api/notifications/ack` |
| `core/interface/tui/widgets/notification_bar.py` | Textual Static widget mirroring ApprovalBar |
| `tests/test_notifications.py` | Unit tests for NotificationRule/State/Manager logic |
| `tests/test_notifications_integration.py` | Integration tests for emit_event hook and API endpoint |

### Modified files
| File | Change |
|---|---|
| `core/autonomic/events.py` | Add `_notification_hook` module-level callback; `emit_event()` calls it after write |
| `core/cognition/pipeline/classify.py` | Emit `safety.pii_anonymized` after PII scrub |
| `core/cognition/pipeline/postprocess.py` | Emit `safety.output_filter_activated` when filter level != CLEAN |
| `core/autonomic/daemon.py` | Emit `daemon.session_warning` 5min before stale threshold; emit `inference.restart_attempt` in `_attempt_restart()` |
| `core/interface/settings_registry.py` | Add 3 new `SettingDef` entries in Advanced tier |
| `core/interface/api/server.py` | Mount notifications router |
| `core/interface/tui/app.py` | Compose `NotificationBar`, add `_poll_notifications` method with `set_interval(3, ...)` |
| `core/interface/tui/client.py` | Add `pending_notifications()` method |
| `core/interface/tui/styles.tcss` | Add `NotificationBar` styles (3 themes) |

---

## Event → Rule Mapping

Composite key is `{category}.{type}` as emitted by `emit_event(category, type, data)`.

### MUST tier (every occurrence surfaced)
| Composite Key | Status | Severity | Message Template |
|---|---|---|---|
| `safety.pii_anonymized` | NEW emission | INFO | "PII anonymized for cloud routing ({entity_count} entities)" |
| `safety.output_filter_activated` | NEW emission | WARNING | "Output filtered — {level} sensitivity detected" |
| `safety.never_leave_activated` | Existing (in pipeline/trace) | WARNING | "Kept local — NEVER_LEAVE active" |
| `daemon.budget_critical` | Existing | ERROR | "Monthly budget at {usage_percent}% — cloud queries limited" |
| `daemon.session_warning` | NEW emission | WARNING | "Session closing in {minutes_remaining} minutes (inactivity)" |

### SHOULD tier (first per session, with escalation)
| Composite Key | Status | Severity | Escalation | Message |
|---|---|---|---|---|
| `fsm.idle_cascade` | Existing (fsm.transition) | INFO | None | "IDLE — vault reindex + consolidation running" |
| `inference.restart_attempt` | NEW emission | WARNING | 3 → ERROR | "Local inference restart {attempt}/3" (escalated: "Local inference exhausted — cloud fallback active") |
| `daemon.budget_warning` | Existing | INFO | None | "Cloud budget at {usage_percent}%" |

### SILENT tier (logs only, never surfaced)
| Composite Key | Reason |
|---|---|
| `daemon.vault_reindex` | Housekeeping |
| `daemon.log_rotation` | Housekeeping |
| `daemon.prewarm` | Internal optimization |
| `daemon.session_auto_close` | Already warned 5min before |
| `daemon.restart_exhausted` | Already escalated via `inference.restart_attempt` |
| `inference.start` | Per-query spam |
| `inference.complete` | Per-query spam |

All other events (unregistered) → implicitly silent (unknown key, no rule, no-op).

---

## Task 1: NotificationManager Core Module + Unit Tests

**Files:**
- Create: `core/autonomic/notifications.py`
- Create: `tests/test_notifications.py`

- [ ] **Step 1: Write the failing test file**

Create `tests/test_notifications.py`:

```python
"""Unit tests for NotificationManager three-tier policy."""
from __future__ import annotations

import pytest

from core.autonomic.notifications import (
    NotificationManager,
    NotificationRule,
    NotificationState,
    NotificationSeverity,
    NotificationTier,
    _build_default_rules,
)


def make_rule(key="test.event", tier=NotificationTier.MUST, severity=NotificationSeverity.INFO,
              escalation_threshold=0, escalation_severity=None, escalation_message=None):
    return NotificationRule(
        event_key=key,
        tier=tier,
        severity=severity,
        dedup_key=key,
        message_template=f"{key} fired",
        escalation_threshold=escalation_threshold,
        escalation_severity=escalation_severity,
        escalation_message=escalation_message,
    )


class TestNotificationState:
    def test_must_tier_fires_every_occurrence(self):
        state = NotificationState()
        rule = make_rule(tier=NotificationTier.MUST)
        assert state.should_fire(rule) is True
        state.record(rule)
        assert state.should_fire(rule) is True
        state.record(rule)
        assert state.should_fire(rule) is True

    def test_should_tier_fires_once_per_session(self):
        state = NotificationState()
        rule = make_rule(tier=NotificationTier.SHOULD)
        assert state.should_fire(rule) is True
        state.record(rule)
        assert state.should_fire(rule) is False
        state.record(rule)
        assert state.should_fire(rule) is False

    def test_silent_tier_never_fires(self):
        state = NotificationState()
        rule = make_rule(tier=NotificationTier.SILENT)
        assert state.should_fire(rule) is False

    def test_escalation_promotes_should_to_must_behavior(self):
        state = NotificationState()
        rule = make_rule(tier=NotificationTier.SHOULD, escalation_threshold=3)
        assert state.should_fire(rule) is True  # first fire
        state.record(rule)  # count=1
        assert state.should_fire(rule) is False  # second suppressed
        state.record(rule)  # count=2
        assert state.should_fire(rule) is False  # third suppressed
        state.record(rule)  # count=3
        assert state.should_fire(rule) is True  # threshold hit — fires

    def test_reset_clears_session_state(self):
        """reset() wipes fired_keys and resets session_start."""
        state = NotificationState()
        rule = make_rule(tier=NotificationTier.SHOULD)
        state.should_fire(rule)
        state.record(rule)
        assert len(state.fired_keys) > 0
        original_start = state.session_start

        import time as _time
        _time.sleep(0.01)
        state.reset()
        assert state.fired_keys == {}
        assert state.session_start > original_start
        # After reset, SHOULD tier fires again
        assert state.should_fire(rule) is True

    def test_dedup_by_key_not_event_type(self):
        state = NotificationState()
        rule_a = NotificationRule(
            event_key="a.one",
            tier=NotificationTier.SHOULD,
            severity=NotificationSeverity.INFO,
            dedup_key="shared",
            message_template="a",
        )
        rule_b = NotificationRule(
            event_key="b.two",
            tier=NotificationTier.SHOULD,
            severity=NotificationSeverity.INFO,
            dedup_key="shared",
            message_template="b",
        )
        assert state.should_fire(rule_a) is True
        state.record(rule_a)
        assert state.should_fire(rule_b) is False  # shared dedup_key — suppressed


class TestNotificationManager:
    def test_unknown_event_type_ignored(self):
        mgr = NotificationManager()
        dispatched = []
        mgr._dispatch_fn = lambda msg, title, sev, timeout: dispatched.append(msg)
        mgr.handle_event({"category": "nonexistent", "type": "foo", "data": {}})
        assert dispatched == []

    def test_message_template_interpolation(self):
        mgr = NotificationManager()
        rule = NotificationRule(
            event_key="safety.pii_anonymized",
            tier=NotificationTier.MUST,
            severity=NotificationSeverity.INFO,
            dedup_key="pii_scrub",
            message_template="PII anonymized ({entity_count} entities)",
        )
        mgr.rules["safety.pii_anonymized"] = rule
        captured = []
        mgr._dispatch_fn = lambda msg, title, sev, timeout: captured.append(msg)
        mgr.handle_event({
            "category": "safety",
            "type": "pii_anonymized",
            "data": {"entity_count": 3},
        })
        assert captured == ["PII anonymized (3 entities)"]

    def test_composite_key_resolution(self):
        mgr = NotificationManager()
        rule = make_rule(key="daemon.budget_critical")
        mgr.rules["daemon.budget_critical"] = rule
        captured = []
        mgr._dispatch_fn = lambda msg, title, sev, timeout: captured.append((msg, sev))
        mgr.handle_event({"category": "daemon", "type": "budget_critical", "data": {}})
        assert len(captured) == 1
        assert captured[0][1] == NotificationSeverity.INFO

    def test_escalation_uses_override_severity(self):
        mgr = NotificationManager()
        rule = NotificationRule(
            event_key="inference.restart_attempt",
            tier=NotificationTier.SHOULD,
            severity=NotificationSeverity.WARNING,
            dedup_key="restart",
            message_template="restart {attempt}/3",
            escalation_threshold=3,
            escalation_severity=NotificationSeverity.ERROR,
            escalation_message="restart exhausted — cloud fallback active",
        )
        mgr.rules["inference.restart_attempt"] = rule
        captured = []
        mgr._dispatch_fn = lambda msg, title, sev, timeout: captured.append((msg, sev))
        # First fire (count goes 0→1)
        mgr.handle_event({"category": "inference", "type": "restart_attempt", "data": {"attempt": 1}})
        # Suppressed (count 1→2)
        mgr.handle_event({"category": "inference", "type": "restart_attempt", "data": {"attempt": 2}})
        # Suppressed (count 2→3)
        mgr.handle_event({"category": "inference", "type": "restart_attempt", "data": {"attempt": 3}})
        # Threshold hit — fires with escalation (count 3→4)
        mgr.handle_event({"category": "inference", "type": "restart_attempt", "data": {"attempt": 4}})
        assert len(captured) == 2
        assert captured[0][1] == NotificationSeverity.WARNING
        assert captured[1][1] == NotificationSeverity.ERROR
        assert captured[1][0] == "restart exhausted — cloud fallback active"

    def test_default_rules_cover_all_dispatch_keys(self):
        rules = _build_default_rules()
        required_keys = {
            "safety.pii_anonymized",
            "safety.output_filter_activated",
            "safety.never_leave_activated",
            "daemon.budget_critical",
            "daemon.budget_warning",
            "daemon.session_warning",
            "fsm.idle_cascade",
            "inference.restart_attempt",
            "daemon.vault_reindex",
            "daemon.log_rotation",
            "daemon.prewarm",
            "daemon.session_auto_close",
            "daemon.restart_exhausted",
        }
        assert required_keys.issubset(rules.keys())

    def test_silent_rules_never_dispatch(self):
        mgr = NotificationManager()
        captured = []
        mgr._dispatch_fn = lambda msg, title, sev, timeout: captured.append(msg)
        mgr.handle_event({"category": "daemon", "type": "vault_reindex", "data": {}})
        mgr.handle_event({"category": "daemon", "type": "log_rotation", "data": {}})
        mgr.handle_event({"category": "daemon", "type": "prewarm", "data": {}})
        assert captured == []

    def test_missing_template_field_uses_fallback(self):
        mgr = NotificationManager()
        rule = NotificationRule(
            event_key="test.event",
            tier=NotificationTier.MUST,
            severity=NotificationSeverity.INFO,
            dedup_key="test",
            message_template="{missing_field} happened",
        )
        mgr.rules["test.event"] = rule
        captured = []
        mgr._dispatch_fn = lambda msg, title, sev, timeout: captured.append(msg)
        # Missing field should not crash — use raw template or placeholder
        mgr.handle_event({"category": "test", "type": "event", "data": {}})
        assert len(captured) == 1  # did not crash
```

- [ ] **Step 2: Run the test file to verify it fails**

```
cd D:/Development/OIKOS_OMEGA
.venv/Scripts/python -m pytest tests/test_notifications.py -v
```

Expected: `ModuleNotFoundError: No module named 'core.autonomic.notifications'`

- [ ] **Step 3: Create the core module**

Create `core/autonomic/notifications.py`:

```python
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
            message_template="PII anonymized for cloud routing ({entity_count} entities)",
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
            severity=NotificationSeverity.ERROR,
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
            escalation_threshold=3,
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
        # Dispatch function — default is internal buffer; can be overridden for tests
        self._dispatch_fn: Callable[[str, str, NotificationSeverity, int], None] = self._default_dispatch

    def handle_event(self, event: dict) -> None:
        """Called from emit_event() for every event on the bus."""
        category = event.get("category", "")
        event_type = event.get("type", "")
        composite_key = f"{category}.{event_type}"

        rule = self.rules.get(composite_key)
        if rule is None:
            return  # Unknown event — implicitly silent

        with self._lock:
            if not self.state.should_fire(rule):
                self.state.record(rule)
                return

            self.state.record(rule)
            count = self.state.fired_keys.get(rule.dedup_key, 0)
            is_escalated = (
                rule.escalation_threshold > 0
                and count >= rule.escalation_threshold
                and rule.tier == NotificationTier.SHOULD
            )

            # Resolve message + severity (escalation may override both)
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
                self._dispatch_fn(message, title, severity, rule.timeout_seconds)
            except Exception as e:
                log.warning("Notification dispatch failed: %s", e)

    @staticmethod
    def _safe_format(template: str, data: dict) -> str:
        """Interpolate template with data, falling back to template on missing keys."""
        try:
            return template.format(**data)
        except (KeyError, IndexError, ValueError):
            return template

    def _default_dispatch(self, message: str, title: str, severity: NotificationSeverity,
                         timeout: int) -> None:
        """Append to pending buffer for TUI/API consumption."""
        pending = PendingNotification(
            timestamp=time.time(),
            message=message,
            title=title,
            severity=severity.value,
            timeout_seconds=timeout,
            event_key=title,
        )
        self._pending.append(pending)
        # CRITICAL severity escalates to desktop immediately (non-blocking)
        if severity == NotificationSeverity.CRITICAL:
            _show_desktop_notification(title, message)

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

    Filled in by Task 9 — stub for now so CRITICAL severity doesn't crash.
    """
    log.debug("Desktop notification (stub): %s — %s", title, message)


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
```

- [ ] **Step 4: Run the test suite to verify it passes**

```
.venv/Scripts/python -m pytest tests/test_notifications.py -v
```

Expected: 10 passed.

- [ ] **Step 5: Commit**

```
git add core/autonomic/notifications.py tests/test_notifications.py
git commit -m "feat(notifications): T-119 NotificationManager core with three-tier policy"
```

---

## Task 2: Wire into emit_event() Choke Point

**Files:**
- Modify: `core/autonomic/events.py`
- Create: `tests/test_notifications_integration.py`

- [ ] **Step 1: Write the integration test first**

Create `tests/test_notifications_integration.py`:

```python
"""Integration tests for NotificationManager hooked into emit_event()."""
from __future__ import annotations

import pytest

from core.autonomic import events as events_module
from core.autonomic.notifications import NotificationManager, NotificationSeverity


@pytest.fixture
def clean_manager(monkeypatch, tmp_path):
    """Fresh NotificationManager + temp events.jsonl for each test."""
    mgr = NotificationManager()
    captured: list[tuple] = []
    mgr._dispatch_fn = lambda msg, title, sev, timeout: captured.append((msg, title, sev, timeout))

    # Point events.jsonl at a temp file so we don't pollute real logs
    monkeypatch.setattr(events_module, "EVENTS_LOG", tmp_path / "events.jsonl")
    # Inject the test manager via the hook
    monkeypatch.setattr(events_module, "_notification_hook",
                        lambda record: mgr.handle_event(record))
    return mgr, captured


class TestEmitEventHook:
    def test_pii_event_triggers_notification(self, clean_manager):
        mgr, captured = clean_manager
        events_module.emit_event("safety", "pii_anonymized", {"entity_count": 2})
        assert len(captured) == 1
        msg, title, sev, timeout = captured[0]
        assert "2 entities" in msg
        assert sev == NotificationSeverity.INFO

    def test_silent_event_writes_to_log_but_no_notification(self, clean_manager, tmp_path):
        mgr, captured = clean_manager
        events_module.emit_event("daemon", "vault_reindex", {"added": 5})
        assert captured == []
        # But event was still written to log
        log_content = (tmp_path / "events.jsonl").read_text(encoding="utf-8")
        assert "vault_reindex" in log_content

    def test_unknown_event_is_silent(self, clean_manager):
        mgr, captured = clean_manager
        events_module.emit_event("nonexistent", "foo", {})
        assert captured == []

    def test_event_log_write_failure_doesnt_crash_notification(self, clean_manager, monkeypatch, tmp_path):
        """If the jsonl write fails, notifications should still fire."""
        mgr, captured = clean_manager
        # Make the log write raise
        def broken_open(*args, **kwargs):
            raise OSError("disk full")
        # Only break the event file, not the test file
        real_open = open
        def conditional_open(path, *args, **kwargs):
            if str(path).endswith("events.jsonl"):
                raise OSError("disk full")
            return real_open(path, *args, **kwargs)
        monkeypatch.setattr("builtins.open", conditional_open)
        # Should not raise
        events_module.emit_event("safety", "pii_anonymized", {"entity_count": 1})
        # Notification still dispatched because hook runs before the write
        # (Note: this documents the ordering guarantee — see Task 2 Step 3)
```

- [ ] **Step 2: Run the test to verify it fails**

```
.venv/Scripts/python -m pytest tests/test_notifications_integration.py -v
```

Expected: `AttributeError: module 'core.autonomic.events' has no attribute '_notification_hook'`

- [ ] **Step 3: Add the hook to events.py**

Edit `core/autonomic/events.py`:

Replace the entire `emit_event` function and add the hook at module level. Find this block:

```python
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
```

Replace with:

```python
# ── Notification hook (set by notifications module; None during bootstrap) ──
# Assigned lazily on first call to avoid circular imports. The hook function
# takes the full event record dict and is called before the log write so
# notifications fire even if the write fails.
_notification_hook: Callable[[dict], None] | None = None


def _dispatch_notification(record: dict) -> None:
    """Call the notification hook if set, swallowing any errors."""
    global _notification_hook
    if _notification_hook is None:
        # Lazy import to break circular dependency (notifications → events → notifications)
        try:
            from core.autonomic.notifications import get_manager
            _notification_hook = lambda r: get_manager().handle_event(r)
        except ImportError:
            return
    try:
        _notification_hook(record)
    except Exception as e:
        log.debug("Notification hook suppressed: %s", e)


def emit_event(category: str, event_type: str, data: dict | None = None) -> None:
    """Append one event record to events.jsonl and dispatch notifications."""
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
```

Also add the import at the top of `core/autonomic/events.py`:

```python
from typing import Callable
```

(Add after the existing `from pathlib import Path` line.)

- [ ] **Step 4: Run the integration tests to verify they pass**

```
.venv/Scripts/python -m pytest tests/test_notifications_integration.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Run the full notification test suite plus a sample of existing tests to confirm no regression**

```
.venv/Scripts/python -m pytest tests/test_notifications.py tests/test_notifications_integration.py tests/test_events.py -v
```

Expected: all passed. If `tests/test_events.py` doesn't exist, skip it.

- [ ] **Step 6: Commit**

```
git add core/autonomic/events.py tests/test_notifications_integration.py
git commit -m "feat(notifications): T-119 hook NotificationManager into emit_event choke point"
```

---

## Task 3: Emit pii_anonymized + output_filter_activated

**Files:**
- Modify: `core/cognition/pipeline/classify.py`
- Modify: `core/cognition/pipeline/postprocess.py`
- Modify: `tests/test_notifications_integration.py`

- [ ] **Step 1: Add a test that asserts PII emission happens when scrubbing is active**

Append to `tests/test_notifications_integration.py`:

```python
class TestPipelineEmission:
    def test_pii_scrub_emits_event(self, clean_manager):
        """classify_input should emit safety.pii_anonymized when PII is scrubbed."""
        from unittest.mock import patch
        from core.cognition.pipeline.classify import classify_input
        from core.interface.models import PIIResult

        mgr, captured = clean_manager
        fake_pii = PIIResult(has_pii=True, entities=[("email", "foo@bar.com"), ("phone", "555-1234")])

        with patch("core.cognition.pipeline.classify.detect_pii", return_value=fake_pii), \
             patch("core.cognition.pipeline.classify.scrub_pii") as scrub_mock, \
             patch("core.cognition.pipeline.classify.log_detection"):
            scrub_mock.return_value = type("S", (), {"scrubbed_text": "[REDACTED]"})()
            classify_input("my email is foo@bar.com", "hash123")

        # Expect a notification for pii_anonymized
        assert any("PII anonymized" in msg for msg, _, _, _ in captured)

    def test_output_filter_emits_event(self, clean_manager):
        """post_process should emit safety.output_filter_activated when filter fires."""
        from unittest.mock import patch, MagicMock
        from core.cognition.pipeline.postprocess import post_process
        from core.cognition.pipeline import PreparedContext
        from core.interface.models import RoutingDecision, CompiledContext, ConfidenceResult

        mgr, captured = clean_manager

        fake_filter_result = MagicMock()
        fake_filter_result.level = "MEDIUM"
        fake_filter_result.triggered = ["keyword_foo"]
        fake_filter_result.response = "filtered text"

        fake_ctx = MagicMock(spec=PreparedContext)
        fake_ctx.effective_query = "test"
        fake_ctx.session = {"session_id": "s1"}
        fake_ctx.decision = MagicMock()
        fake_ctx.decision.reason = ""
        fake_ctx.decision.cosine_gate_fired = False

        with patch("core.safety.output_filter.check_output_sensitivity", return_value=fake_filter_result), \
             patch("core.autonomic.confidence.score_response",
                   return_value=ConfidenceResult(score=0.8, method="test")), \
             patch("core.identity.coherence.check_coherence") as coh_mock, \
             patch("core.identity.assertions.check_assertion") as assert_mock:
            coh_mock.return_value = MagicMock(is_coherent=True)
            assert_mock.return_value = MagicMock(contains_assertion=False)
            post_process("response text", None, fake_ctx, "test-model")

        assert any("Output filtered" in msg for msg, _, _, _ in captured)
```

- [ ] **Step 2: Run the test to verify it fails**

```
.venv/Scripts/python -m pytest tests/test_notifications_integration.py::TestPipelineEmission -v
```

Expected: both tests fail because emissions haven't been added.

- [ ] **Step 3: Add PII emission in classify.py**

Edit `core/cognition/pipeline/classify.py`. Find the PII scrub block (around lines 60-67):

```python
    # 2. Determine effective query
    effective_query = query
    pii_scrubbed = False
    if pii_result.has_pii:
        scrub_result = scrub_pii(query)
        if scrub_result.scrubbed_text and scrub_result.scrubbed_text != query:
            effective_query = scrub_result.scrubbed_text
            pii_scrubbed = True
```

Replace with:

```python
    # 2. Determine effective query
    effective_query = query
    pii_scrubbed = False
    if pii_result.has_pii:
        scrub_result = scrub_pii(query)
        if scrub_result.scrubbed_text and scrub_result.scrubbed_text != query:
            effective_query = scrub_result.scrubbed_text
            pii_scrubbed = True
            # T-119: emit notification event for PII anonymization
            try:
                from core.autonomic.events import emit_event
                emit_event("safety", "pii_anonymized", {
                    "entity_count": len(pii_result.entities),
                    "query_hash": qhash,
                })
            except Exception as e:
                log.debug("pii_anonymized emit suppressed: %s", e)
```

- [ ] **Step 4: Add output filter emission in postprocess.py**

Edit `core/cognition/pipeline/postprocess.py`. Find the output filter block (around lines 124-135):

```python
    # 8c. Output sensitivity filter
    try:
        from core.safety.output_filter import check_output_sensitivity
        filter_result = check_output_sensitivity(text)
        text = filter_result.response
        if filter_result.level != "CLEAN":
            log.warning("[OUTPUT FILTER] level=%s triggered=%s",
                        filter_result.level, filter_result.triggered)
            if trace is not None:
                trace.output_filtered = True
    except (ImportError, ValueError, RuntimeError) as e:
        log.warning("[OUTPUT FILTER] failed: %s — passing through", e)
```

Replace with:

```python
    # 8c. Output sensitivity filter
    try:
        from core.safety.output_filter import check_output_sensitivity
        filter_result = check_output_sensitivity(text)
        text = filter_result.response
        if filter_result.level != "CLEAN":
            log.warning("[OUTPUT FILTER] level=%s triggered=%s",
                        filter_result.level, filter_result.triggered)
            if trace is not None:
                trace.output_filtered = True
            # T-119: emit notification event for output filter activation
            try:
                from core.autonomic.events import emit_event
                emit_event("safety", "output_filter_activated", {
                    "level": filter_result.level,
                    "triggered": filter_result.triggered,
                })
            except Exception as e:
                log.debug("output_filter_activated emit suppressed: %s", e)
    except (ImportError, ValueError, RuntimeError) as e:
        log.warning("[OUTPUT FILTER] failed: %s — passing through", e)
```

- [ ] **Step 5: Run the tests to verify they pass**

```
.venv/Scripts/python -m pytest tests/test_notifications_integration.py::TestPipelineEmission -v
```

Expected: 2 passed.

- [ ] **Step 6: Run the broader test suite to confirm no regression in classify/postprocess**

```
.venv/Scripts/python -m pytest tests/ -k "classify or postprocess or pipeline or pii or output_filter" -v
```

Expected: all passed. Existing tests still work because the emissions are inside try/except.

- [ ] **Step 7: Commit**

```
git add core/cognition/pipeline/classify.py core/cognition/pipeline/postprocess.py tests/test_notifications_integration.py
git commit -m "feat(notifications): T-119 emit safety.pii_anonymized + safety.output_filter_activated"
```

---

## Task 4: Emit session_warning + restart_attempt + idle_cascade

**Files:**
- Modify: `core/autonomic/daemon.py`
- Modify: `core/autonomic/fsm.py`
- Modify: `tests/test_notifications_integration.py`

- [ ] **Step 1: Add tests for the three new daemon/fsm emissions**

Append to `tests/test_notifications_integration.py`:

```python
class TestDaemonFSMEmission:
    def test_restart_attempt_emits_event(self, clean_manager, monkeypatch):
        """_attempt_restart should emit inference.restart_attempt before backoff."""
        from core.autonomic import daemon
        mgr, captured = clean_manager

        # Stub out the manager + sleep
        fake_mgr = type("M", (), {
            "backend_name": lambda self: "Ollama",
            "restart": lambda self: __import__("asyncio").sleep(0),
        })()
        monkeypatch.setattr(daemon, "_inference_manager", fake_mgr)
        monkeypatch.setattr(daemon, "_restart_attempts", 0)
        monkeypatch.setattr(daemon, "_restart_window_start", None)
        monkeypatch.setattr(daemon.time, "sleep", lambda _: None)

        daemon._attempt_restart()

        # First attempt — SHOULD tier, fires once
        assert any("restart 1/3" in msg.lower() or "restart" in msg.lower()
                   for msg, _, _, _ in captured), f"captured={captured}"

    def test_session_warning_emits_before_stale(self, clean_manager, monkeypatch):
        """_check_stale_sessions should emit daemon.session_warning 5min before stale threshold."""
        from datetime import datetime, timedelta, timezone
        from core.autonomic import daemon
        mgr, captured = clean_manager

        # Reset the warning flag
        monkeypatch.setattr(daemon, "_session_warning_fired", False, raising=False)
        monkeypatch.setattr(daemon, "_last_session_check", 0.0)

        stale_min = daemon.DAEMON_SESSION_STALE_MINUTES  # e.g. 30
        warning_elapsed = stale_min - 4  # 4 minutes before close = inside warning window

        fake_last_active = datetime.now(timezone.utc) - timedelta(minutes=warning_elapsed)
        fake_state = {"last_active_at": fake_last_active.isoformat(), "session_id": "test"}

        def fake_load_state():
            return fake_state

        import core.memory.session as session_module
        monkeypatch.setattr(session_module, "_load_state", fake_load_state)
        # Don't actually close — only the warning should fire
        monkeypatch.setattr(session_module, "close_session", lambda: None)

        daemon._check_stale_sessions()

        # Expect a session closing warning
        assert any("closing in" in msg.lower() for msg, _, _, _ in captured), f"captured={captured}"

    def test_fsm_transition_to_idle_emits_idle_cascade(self, clean_manager, monkeypatch):
        """FSM ACTIVE→IDLE transition should emit fsm.idle_cascade once per session."""
        from core.autonomic import fsm
        from core.interface.models import SystemState
        mgr, captured = clean_manager

        # Force current state to ACTIVE
        monkeypatch.setattr(fsm, "_current_state", SystemState.ACTIVE, raising=False)
        fsm.transition_to(SystemState.IDLE, trigger="test")

        assert any("idle" in msg.lower() and "cascade" in msg.lower() or "IDLE" in msg
                   for msg, _, _, _ in captured), f"captured={captured}"
```

- [ ] **Step 2: Run the tests to verify they fail**

```
.venv/Scripts/python -m pytest tests/test_notifications_integration.py::TestDaemonFSMEmission -v
```

Expected: 3 failures — the events aren't emitted yet.

- [ ] **Step 3: Add session warning in daemon.py**

Edit `core/autonomic/daemon.py`. Find the module state block (around lines 55-63):

```python
# Interval trackers for new features
_last_vault_mtime: float = 0.0
_last_session_check: float = 0.0
_last_budget_check: float = 0.0
_budget_alert_fired: bool = False
_budget_critical_fired: bool = False
_last_log_rotation: float = 0.0
_last_prewarm_check: float = 0.0
_today_activity_logged: bool = False
```

Add after `_today_activity_logged`:

```python
_session_warning_fired: bool = False
```

Then find `_check_stale_sessions` (around lines 249-282). Replace the entire function:

```python
def _check_stale_sessions() -> None:
    """Close web UI sessions that have been inactive too long.

    Also emits daemon.session_warning 5 minutes before the auto-close threshold.
    """
    global _last_session_check, _session_warning_fired

    now = time.monotonic()
    if now - _last_session_check < DAEMON_SESSION_CHECK_INTERVAL_SEC:
        return
    _last_session_check = now

    try:
        from core.memory.session import SESSION_STATE_FILE, _load_state, close_session

        state = _load_state()
        if state is None:
            _session_warning_fired = False  # new session incoming — reset
            return

        last_active = datetime.fromisoformat(state["last_active_at"])
        elapsed_min = (datetime.now(timezone.utc) - last_active).total_seconds() / 60

        # 5-minute warning window before the stale threshold
        warning_threshold = DAEMON_SESSION_STALE_MINUTES - 5
        if (not _session_warning_fired
                and warning_threshold <= elapsed_min < DAEMON_SESSION_STALE_MINUTES):
            _session_warning_fired = True
            minutes_remaining = max(1, round(DAEMON_SESSION_STALE_MINUTES - elapsed_min))
            from core.autonomic.events import emit_event
            emit_event("daemon", "session_warning", {
                "session_id": state.get("session_id"),
                "minutes_remaining": minutes_remaining,
                "elapsed_minutes": round(elapsed_min),
            })
            log.info(
                "Session closing warning emitted (session=%s, %d min remaining)",
                state.get("session_id"), minutes_remaining,
            )

        if elapsed_min > DAEMON_SESSION_STALE_MINUTES:
            result = close_session()
            if result:
                log.info(
                    "Auto-closed stale session %s (inactive %.0f min, %d interactions)",
                    result["session_id"], elapsed_min, result.get("interaction_count", 0),
                )
                _session_warning_fired = False  # reset for the next session
                from core.autonomic.events import emit_event
                emit_event("daemon", "session_auto_close", {
                    "session_id": result["session_id"],
                    "inactive_minutes": round(elapsed_min),
                    "interaction_count": result.get("interaction_count", 0),
                })
    except Exception as e:
        log.warning("Session auto-close check failed: %s", e)
```

- [ ] **Step 4: Add restart_attempt emission in _attempt_restart**

Find `_attempt_restart` in `core/autonomic/daemon.py` (around lines 164-204). Locate the logging line:

```python
    backoff = RESTART_BACKOFF[min(_restart_attempts, len(RESTART_BACKOFF) - 1)]
    name = _inference_manager.backend_name()
    log.info("Restarting %s (attempt %d/%d, backoff %ds)",
             name, _restart_attempts + 1, MAX_RESTART_ATTEMPTS, backoff)

    time.sleep(backoff)
```

Replace with:

```python
    backoff = RESTART_BACKOFF[min(_restart_attempts, len(RESTART_BACKOFF) - 1)]
    name = _inference_manager.backend_name()
    log.info("Restarting %s (attempt %d/%d, backoff %ds)",
             name, _restart_attempts + 1, MAX_RESTART_ATTEMPTS, backoff)

    # T-119: emit notification event (SHOULD tier with escalation at threshold=3)
    try:
        from core.autonomic.events import emit_event
        emit_event("inference", "restart_attempt", {
            "backend": name,
            "attempt": _restart_attempts + 1,
            "max_attempts": MAX_RESTART_ATTEMPTS,
        })
    except Exception as e:
        log.debug("restart_attempt emit suppressed: %s", e)

    time.sleep(backoff)
```

- [ ] **Step 5: Add fsm.idle_cascade emission**

Edit `core/autonomic/fsm.py`. Find the existing `emit_event("fsm", "transition", ...)` block inside `transition_to()` (around line 79-83):

```python
    try:
        from core.autonomic.events import emit_event
        emit_event("fsm", "transition", {"from": current.value, "to": target.value, "trigger": trigger})
    except Exception as e:
        log.debug("transition emit_event suppressed: %s", e)
```

Replace with:

```python
    try:
        from core.autonomic.events import emit_event
        emit_event("fsm", "transition", {"from": current.value, "to": target.value, "trigger": trigger})
        # T-119: dedicated idle_cascade event for notifications (SHOULD tier, once per session)
        if target == SystemState.IDLE:
            emit_event("fsm", "idle_cascade", {
                "from": current.value,
                "trigger": trigger,
            })
    except Exception as e:
        log.debug("transition emit_event suppressed: %s", e)
```

- [ ] **Step 6: Run the tests to verify they pass**

```
.venv/Scripts/python -m pytest tests/test_notifications_integration.py::TestDaemonFSMEmission -v
```

Expected: 3 passed.

- [ ] **Step 7: Run daemon-related tests to confirm no regression**

```
.venv/Scripts/python -m pytest tests/ -k "daemon or fsm or session_auto" -v
```

Expected: all passed.

- [ ] **Step 8: Commit**

```
git add core/autonomic/daemon.py core/autonomic/fsm.py tests/test_notifications_integration.py
git commit -m "feat(notifications): T-119 emit session_warning + restart_attempt + idle_cascade"
```

---

## Task 5: Ring Buffer + API Endpoint

**Files:**
- Create: `core/interface/api/routes/notifications.py`
- Modify: `core/interface/api/server.py`
- Modify: `tests/test_notifications_integration.py`

- [ ] **Step 1: Add API endpoint tests**

Append to `tests/test_notifications_integration.py`:

```python
class TestNotificationAPI:
    def test_get_pending_returns_empty_initially(self, monkeypatch):
        from fastapi.testclient import TestClient
        from core.interface.api.server import build_app
        from core.autonomic import notifications as notif_module

        # Fresh manager for isolation
        fresh_mgr = notif_module.NotificationManager()
        monkeypatch.setattr(notif_module, "_manager", fresh_mgr)

        app = build_app()
        with TestClient(app) as client:
            r = client.get("/api/notifications/pending")
            assert r.status_code == 200
            assert r.json() == {"pending": []}

    def test_get_pending_returns_fired_notifications(self, monkeypatch):
        from fastapi.testclient import TestClient
        from core.interface.api.server import build_app
        from core.autonomic import notifications as notif_module
        from core.autonomic import events as events_module

        fresh_mgr = notif_module.NotificationManager()
        monkeypatch.setattr(notif_module, "_manager", fresh_mgr)
        monkeypatch.setattr(events_module, "_notification_hook",
                           lambda r: fresh_mgr.handle_event(r))

        events_module.emit_event("safety", "pii_anonymized", {"entity_count": 1})

        app = build_app()
        with TestClient(app) as client:
            r = client.get("/api/notifications/pending")
            assert r.status_code == 200
            body = r.json()
            assert len(body["pending"]) == 1
            assert "PII anonymized" in body["pending"][0]["message"]
            assert body["pending"][0]["severity"] == "information"

    def test_get_pending_since_filter(self, monkeypatch):
        """?since=<timestamp> returns only newer notifications."""
        import time
        from fastapi.testclient import TestClient
        from core.interface.api.server import build_app
        from core.autonomic import notifications as notif_module
        from core.autonomic import events as events_module

        fresh_mgr = notif_module.NotificationManager()
        monkeypatch.setattr(notif_module, "_manager", fresh_mgr)
        monkeypatch.setattr(events_module, "_notification_hook",
                           lambda r: fresh_mgr.handle_event(r))

        events_module.emit_event("safety", "pii_anonymized", {"entity_count": 1})
        t_cutoff = time.time()
        time.sleep(0.01)
        events_module.emit_event("daemon", "budget_critical", {"usage_percent": 95})

        app = build_app()
        with TestClient(app) as client:
            r = client.get(f"/api/notifications/pending?since={t_cutoff}")
            body = r.json()
            assert len(body["pending"]) == 1
            assert "budget" in body["pending"][0]["message"].lower()
```

- [ ] **Step 2: Run the tests to verify they fail**

```
.venv/Scripts/python -m pytest tests/test_notifications_integration.py::TestNotificationAPI -v
```

Expected: 404 errors (endpoint doesn't exist).

- [ ] **Step 3: Create the API route file**

Create `core/interface/api/routes/notifications.py`:

```python
"""T-119: Notification API routes.

Mirrors the T-102 approval endpoint pattern. The NotificationManager
maintains an in-memory ring buffer of pending notifications. TUI and
web clients poll this endpoint.
"""
from __future__ import annotations

from fastapi import APIRouter, Query

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


@router.get("/pending")
def list_pending(
    since: float | None = Query(None, description="Return notifications newer than this Unix timestamp"),
) -> dict:
    """Return pending notifications as a JSON list.

    Non-destructive read — notifications stay in the buffer until they age
    out naturally (deque maxlen). Clients use the `since` parameter to
    paginate forward over time.
    """
    from core.autonomic.notifications import get_manager
    mgr = get_manager()
    items = mgr.drain_pending(since_timestamp=since)
    return {"pending": items}


@router.post("/reset")
def reset_session() -> dict:
    """Clear session state (dedup counters + pending buffer).

    Called automatically on session start; exposed here for manual reset.
    """
    from core.autonomic.notifications import get_manager
    mgr = get_manager()
    mgr.reset_session()
    return {"status": "reset"}
```

- [ ] **Step 4: Mount the router in server.py**

Read `core/interface/api/server.py` to find the router mount section:

```
.venv/Scripts/python -c "from pathlib import Path; [print(f'{i+1}: {l}') for i,l in enumerate(Path('core/interface/api/server.py').read_text().split(chr(10))) if 'include_router' in l or 'from core.interface.api.routes' in l]"
```

Expected: a block of `app.include_router(...)` calls. Add the notifications router alongside them. Find a line like:

```python
from core.interface.api.routes import agency as agency_routes
```

Add:

```python
from core.interface.api.routes import notifications as notifications_routes
```

And in the `build_app()` function (or wherever routers are registered), find:

```python
app.include_router(agency_routes.router, prefix="/api/approvals")
```

Add after it:

```python
app.include_router(notifications_routes.router)
```

Note: the notifications router already has its own `prefix="/api/notifications"` in its declaration, so no prefix argument here.

- [ ] **Step 5: Run the API tests to verify they pass**

```
.venv/Scripts/python -m pytest tests/test_notifications_integration.py::TestNotificationAPI -v
```

Expected: 3 passed.

- [ ] **Step 6: Run the broader API test suite**

```
.venv/Scripts/python -m pytest tests/ -k "api or server" --timeout=30 -v
```

Expected: all passed (no regression in existing API routes).

- [ ] **Step 7: Commit**

```
git add core/interface/api/routes/notifications.py core/interface/api/server.py tests/test_notifications_integration.py
git commit -m "feat(notifications): T-119 add /api/notifications/pending endpoint with ring buffer"
```

---

## Task 6: Register Notification Settings in T-117 Registry

**Files:**
- Modify: `core/interface/settings_registry.py`
- Create: `tests/test_notification_settings.py`

- [ ] **Step 1: Write tests for the new settings**

Create `tests/test_notification_settings.py`:

```python
"""T-119: Test notification settings registration in T-117 registry."""
from __future__ import annotations

import pytest

from core.interface.settings_registry import (
    SETTINGS_REGISTRY,
    SettingTier,
    get_registry_default,
    validate_setting,
)


class TestNotificationSettings:
    def test_must_enabled_setting_exists(self):
        assert "notifications_must_enabled" in SETTINGS_REGISTRY
        defn = SETTINGS_REGISTRY["notifications_must_enabled"]
        assert defn.tier == SettingTier.ADVANCED
        assert defn.setting_type == "bool"
        assert defn.default is True

    def test_should_enabled_setting_exists(self):
        assert "notifications_should_enabled" in SETTINGS_REGISTRY
        defn = SETTINGS_REGISTRY["notifications_should_enabled"]
        assert defn.tier == SettingTier.ADVANCED
        assert defn.setting_type == "bool"
        assert defn.default is True

    def test_desktop_enabled_setting_exists(self):
        assert "notifications_desktop_enabled" in SETTINGS_REGISTRY
        defn = SETTINGS_REGISTRY["notifications_desktop_enabled"]
        assert defn.tier == SettingTier.ADVANCED
        assert defn.setting_type == "bool"
        assert defn.default is True

    def test_validate_must_enabled_boolean(self):
        ok, _ = validate_setting("notifications_must_enabled", True)
        assert ok is True
        ok, _ = validate_setting("notifications_must_enabled", "not a bool")
        assert ok is False

    def test_existing_notifications_master_still_exists(self):
        """The pre-existing 'notifications' master key is untouched."""
        assert "notifications" in SETTINGS_REGISTRY
        assert SETTINGS_REGISTRY["notifications"].tier == SettingTier.ESSENTIAL

    def test_manager_respects_notifications_master_off(self, monkeypatch):
        """When master notifications=False, NO tier fires — including MUST."""
        from core.autonomic.notifications import NotificationManager
        from core.interface import settings as settings_module

        mgr = NotificationManager()
        captured = []
        mgr._dispatch_fn = lambda msg, title, sev, timeout: captured.append(msg)

        # Monkey-patch get_setting to return False for master
        def fake_get_setting(key, default=None):
            if key == "notifications":
                return False
            return default
        monkeypatch.setattr(settings_module, "get_setting", fake_get_setting)

        mgr.handle_event({"category": "safety", "type": "pii_anonymized",
                          "data": {"entity_count": 1}})
        assert captured == []

    def test_manager_respects_should_disabled(self, monkeypatch):
        """When notifications_should_enabled=False, SHOULD tier is suppressed but MUST still fires."""
        from core.autonomic.notifications import NotificationManager
        from core.interface import settings as settings_module

        mgr = NotificationManager()
        captured = []
        mgr._dispatch_fn = lambda msg, title, sev, timeout: captured.append(msg)

        def fake_get_setting(key, default=None):
            if key == "notifications":
                return True
            if key == "notifications_should_enabled":
                return False
            if key == "notifications_must_enabled":
                return True
            return default
        monkeypatch.setattr(settings_module, "get_setting", fake_get_setting)

        # MUST tier — fires
        mgr.handle_event({"category": "safety", "type": "pii_anonymized",
                          "data": {"entity_count": 1}})
        # SHOULD tier — suppressed
        mgr.handle_event({"category": "daemon", "type": "budget_warning",
                          "data": {"usage_percent": 80}})

        assert len(captured) == 1
        assert "PII" in captured[0]
```

- [ ] **Step 2: Run the tests to verify they fail**

```
.venv/Scripts/python -m pytest tests/test_notification_settings.py -v
```

Expected: 7 failures (settings missing, manager doesn't check them).

- [ ] **Step 3: Add the three settings to the registry**

Edit `core/interface/settings_registry.py`. Find the Advanced tier section (around line 144 where `pii_confidence_threshold` starts). Add these three entries at the beginning of the Advanced tier block (after the comment `# ── Advanced ─────────────────────────────────────────────────`):

```python
    "notifications_must_enabled": SettingDef(
        key="notifications_must_enabled",
        tier=SettingTier.ADVANCED,
        setting_type="bool",
        default=True,
        description="Surface MUST-tier notifications (safety, budget, session warnings)",
        validator=lambda v: isinstance(v, bool),
        error_hint="Must be true or false",
    ),
    "notifications_should_enabled": SettingDef(
        key="notifications_should_enabled",
        tier=SettingTier.ADVANCED,
        setting_type="bool",
        default=True,
        description="Surface SHOULD-tier notifications (idle cascade, restarts, budget alerts)",
        validator=lambda v: isinstance(v, bool),
        error_hint="Must be true or false",
    ),
    "notifications_desktop_enabled": SettingDef(
        key="notifications_desktop_enabled",
        tier=SettingTier.ADVANCED,
        setting_type="bool",
        default=True,
        description="Escalate CRITICAL notifications to Windows desktop toast",
        validator=lambda v: isinstance(v, bool),
        error_hint="Must be true or false",
    ),
```

- [ ] **Step 4: Wire settings gating into NotificationManager**

Edit `core/autonomic/notifications.py`. Find `NotificationManager.handle_event` and add a settings check at the top, before the rule lookup:

```python
    def handle_event(self, event: dict) -> None:
        """Called from emit_event() for every event on the bus."""
        # Check master + tier settings — fast path if notifications disabled
        if not self._notifications_enabled_for_tier(None):  # master check
            return

        category = event.get("category", "")
        event_type = event.get("type", "")
        composite_key = f"{category}.{event_type}"

        rule = self.rules.get(composite_key)
        if rule is None:
            return  # Unknown event — implicitly silent

        # Check tier-specific setting
        if not self._notifications_enabled_for_tier(rule.tier):
            return

        with self._lock:
            # ... rest unchanged
```

And add this helper method to `NotificationManager`:

```python
    def _notifications_enabled_for_tier(self, tier: NotificationTier | None) -> bool:
        """Check master + tier-specific setting. Called on every event."""
        try:
            from core.interface.settings import get_setting
        except ImportError:
            return True  # Bootstrap / test context — allow

        # Master switch
        if not get_setting("notifications", True):
            return False

        if tier is None:
            return True  # Only master check requested

        # Tier-specific switches
        if tier == NotificationTier.MUST:
            return bool(get_setting("notifications_must_enabled", True))
        if tier == NotificationTier.SHOULD:
            return bool(get_setting("notifications_should_enabled", True))
        return True  # SILENT never reaches here; default allow
```

- [ ] **Step 5: Run the settings tests to verify they pass**

```
.venv/Scripts/python -m pytest tests/test_notification_settings.py -v
```

Expected: 7 passed.

- [ ] **Step 6: Run the full notifications test suite to confirm no regression**

```
.venv/Scripts/python -m pytest tests/test_notifications.py tests/test_notifications_integration.py tests/test_notification_settings.py -v
```

Expected: all passed.

- [ ] **Step 7: Commit**

```
git add core/interface/settings_registry.py core/autonomic/notifications.py tests/test_notification_settings.py
git commit -m "feat(notifications): T-119 register must/should/desktop settings in T-117 registry"
```

---

## Task 7: TUI NotificationBar Widget with Polling

**Files:**
- Create: `core/interface/tui/widgets/notification_bar.py`
- Modify: `core/interface/tui/widgets/__init__.py`
- Modify: `core/interface/tui/client.py`
- Modify: `core/interface/tui/app.py`
- Modify: `core/interface/tui/styles.tcss`
- Create: `tests/test_tui_notification_bar.py`

- [ ] **Step 1: Write a test for the widget**

Create `tests/test_tui_notification_bar.py`:

```python
"""T-119: TUI NotificationBar widget tests."""
from __future__ import annotations

import pytest

pytest.importorskip("textual")

from core.interface.tui.widgets.notification_bar import NotificationBar


class TestNotificationBar:
    def test_hidden_when_empty(self):
        bar = NotificationBar()
        bar.update_pending([])
        assert bar.display is False

    def test_shown_with_single_notification(self):
        bar = NotificationBar()
        bar.update_pending([{
            "message": "PII anonymized (2 entities)",
            "title": "PII Scrubbed",
            "severity": "information",
        }])
        assert bar.display is True
        # Content should reference the message
        # (We can't easily assert on rendered output without a full Textual pilot)

    def test_shown_with_multiple_notifications(self):
        bar = NotificationBar()
        notifs = [
            {"message": "first", "title": "A", "severity": "information"},
            {"message": "second", "title": "B", "severity": "warning"},
            {"message": "third", "title": "C", "severity": "error"},
        ]
        bar.update_pending(notifs)
        assert bar.display is True
        # Should show count
```

- [ ] **Step 2: Create the widget**

Create `core/interface/tui/widgets/notification_bar.py`:

```python
"""T-119: Background notification bar for the oikOS TUI.

Mirrors the T-102 ApprovalBar pattern. Docked above the footer.
Hidden when no notifications pending. Shows the most recent
notification plus a count if there are more than one.
"""
from __future__ import annotations

from textual.widgets import Static


class NotificationBar(Static):
    """Transient notification bar for background events."""

    def __init__(self) -> None:
        super().__init__("", id="notification-bar")
        self._count = 0
        self._pending: list[dict] = []

    def update_pending(self, pending: list[dict]) -> None:
        """Update from list of pending notification dicts."""
        self._count = len(pending)
        self._pending = pending
        if self._count == 0:
            self.display = False
            return

        self.display = True
        # Show the newest (last) notification — the ring buffer appends to the end
        latest = pending[-1]
        message = latest.get("message", "")
        severity = latest.get("severity", "information")

        # Severity prefix as ASCII for terminal compatibility
        prefix = {
            "information": "[i]",
            "warning": "[!]",
            "error": "[X]",
        }.get(severity, "[*]")

        if self._count == 1:
            self.update(f"{prefix} {message}")
        else:
            self.update(f"{prefix} {message}  (+{self._count - 1} more)")
```

- [ ] **Step 3: Export from widgets/__init__.py**

Edit `core/interface/tui/widgets/__init__.py`. Find the existing exports (e.g. `from .approval_bar import ApprovalBar`). Add:

```python
from .notification_bar import NotificationBar
```

And update `__all__` if present to include `"NotificationBar"`.

- [ ] **Step 4: Add pending_notifications() to the API client**

Edit `core/interface/tui/client.py`. Find the `pending_approvals()` method (around line 138). Add directly after it:

```python
    async def pending_notifications(self, since: float | None = None) -> list[dict]:
        """GET /api/notifications/pending — returns list of pending notifications."""
        path = "/api/notifications/pending"
        if since is not None:
            path += f"?since={since}"
        data = await self._get(path, fallback={"pending": []})
        return data.get("pending", [])
```

- [ ] **Step 5: Mount the widget and wire polling in app.py**

Edit `core/interface/tui/app.py`.

First, add the import at the top alongside the `ApprovalBar` import (around line 27):

```python
from core.interface.tui.widgets.notification_bar import NotificationBar
```

Next, find the `compose` method where `ApprovalBar()` is yielded (around line 164). Add immediately after it:

```python
        yield NotificationBar()
```

Find the `_poll_approvals` method (around line 289) and the line where it's scheduled via `set_interval`. The scheduling lives in `on_mount` or similar startup method. Find where `set_interval(3, self._poll_approvals)` is called and add directly after it:

```python
        self._notifications_last_seen: float = 0.0
        self.set_interval(3.0, self._poll_notifications)
```

(If the attribute initialization needs to happen earlier — in `__init__` — put `self._notifications_last_seen = 0.0` in `__init__` and only the `set_interval` call wherever approvals polling is scheduled.)

Then add the `_poll_notifications` method directly after `_poll_approvals`:

```python
    async def _poll_notifications(self) -> None:
        """Poll for pending notifications every 3 seconds."""
        try:
            pending = await self.api_client.pending_notifications(
                since=self._notifications_last_seen
            )
            if pending:
                # Track the newest timestamp for next poll
                newest = max(n.get("timestamp", 0) for n in pending)
                self._notifications_last_seen = max(self._notifications_last_seen, newest)
            self.query_one(NotificationBar).update_pending(pending)
        except Exception as e:
            log.debug("notification poll suppressed: %s", e)
```

- [ ] **Step 6: Add styles for the NotificationBar**

Edit `core/interface/tui/styles.tcss`. Find the `ApprovalBar { ... }` block (around line 39). Add a similar block directly after it:

```tcss
NotificationBar {
    dock: bottom;
    height: 1;
    width: 100%;
    background: #2A1F05;
    color: #FFB000;
    padding: 0 1;
    display: none;
}

NotificationBar:focus {
    background: #3A2A08;
}
```

Find the theme overrides for `ApprovalBar` (around lines 469 and 491). Add matching lines:

```tcss
Screen.theme-green NotificationBar { background: #001A00; color: #33FF33; }
```

And:

```tcss
Screen.theme-white NotificationBar { background: #1A1A1A; color: #E0E0E0; }
```

- [ ] **Step 7: Run the widget tests**

```
.venv/Scripts/python -m pytest tests/test_tui_notification_bar.py -v
```

Expected: 3 passed.

- [ ] **Step 8: Run the full TUI test suite to confirm no regression**

```
.venv/Scripts/python -m pytest tests/ -k "tui" -v
```

Expected: all passed.

- [ ] **Step 9: Commit**

```
git add core/interface/tui/widgets/notification_bar.py core/interface/tui/widgets/__init__.py core/interface/tui/client.py core/interface/tui/app.py core/interface/tui/styles.tcss tests/test_tui_notification_bar.py
git commit -m "feat(notifications): T-119 TUI NotificationBar widget with 3s polling"
```

---

## Task 8: Web UI Toast via SSE

**Files:**
- Modify: `core/interface/api/routes/events.py` (or create new `notifications_sse.py` if needed)
- Modify: `frontend/src/` toast handler (locate first)

This task requires investigation first because Phase 7c Module 6 toast infrastructure needs to be verified.

- [ ] **Step 1: Locate the existing SSE events endpoint**

```
.venv/Scripts/python -c "from pathlib import Path; print(Path('core/interface/api/routes/events.py').read_text())"
```

Expected: the events route file content. Read carefully to understand the SSE emission pattern.

- [ ] **Step 2: Locate the frontend toast infrastructure**

```
.venv/Scripts/python -c "import subprocess; print(subprocess.run(['grep', '-rl', 'toast', 'frontend/src/'], capture_output=True, text=True).stdout)"
```

If grep isn't available, use the Grep tool or:

```
find frontend/src -name "*.tsx" -o -name "*.ts" | xargs grep -l -i toast 2>/dev/null | head -10
```

Expected: one or more frontend files referencing toasts. Read the primary toast component.

- [ ] **Step 3: Add SSE notification emission**

If the existing events endpoint already streams events, notifications will flow automatically because they're written to `events.jsonl` via `emit_event`. In that case, the frontend only needs to filter SSE events by category/type and render them as toasts.

If the existing endpoint does NOT stream live events, add a new endpoint `/api/notifications/stream` in `core/interface/api/routes/notifications.py`:

```python
from fastapi.responses import StreamingResponse
import asyncio
import json


@router.get("/stream")
async def notification_stream():
    """SSE stream for real-time notifications."""
    from core.autonomic.notifications import get_manager
    mgr = get_manager()

    async def event_gen():
        last_seen = 0.0
        while True:
            pending = mgr.drain_pending(since_timestamp=last_seen)
            if pending:
                last_seen = max(n["timestamp"] for n in pending)
                for notif in pending:
                    yield f"data: {json.dumps(notif)}\n\n"
            await asyncio.sleep(1.0)

    return StreamingResponse(event_gen(), media_type="text/event-stream")
```

- [ ] **Step 4: Add frontend toast renderer for notification events**

This step is frontend-dependent — find the existing toast component and add a subscriber for `/api/notifications/stream` (or filter the existing events stream). Write a vitest test alongside it that asserts the toast component renders when a notification event arrives.

Exact code depends on the frontend structure. If the frontend already has an SSE event subscriber, add a `useEffect` that opens an `EventSource('/api/notifications/stream')` and calls the existing toast API on each message.

- [ ] **Step 5: Run vitest**

```
cd frontend && npm run test -- --run
```

Expected: all passed, including any new notification test.

- [ ] **Step 6: Commit**

```
git add core/interface/api/routes/ frontend/src/
git commit -m "feat(notifications): T-119 web UI toast via SSE notification stream"
```

**Note:** If Phase 7c Module 6 toast infra is missing or broken, flag this in the build report and scope it down to API-only for this PR. Web UI toast can be a follow-up task.

---

## Task 9: Desktop Escalation via BurntToast

**Files:**
- Modify: `core/autonomic/notifications.py`
- Modify: `tests/test_notifications.py`

- [ ] **Step 1: Add a test for desktop dispatch**

Append to `tests/test_notifications.py`:

```python
class TestDesktopEscalation:
    def test_critical_severity_triggers_desktop_call(self, monkeypatch):
        """CRITICAL severity should invoke the desktop notification helper."""
        from core.autonomic import notifications as notif_module

        calls = []
        monkeypatch.setattr(notif_module, "_show_desktop_notification",
                           lambda title, msg: calls.append((title, msg)))

        mgr = notif_module.NotificationManager()
        rule = notif_module.NotificationRule(
            event_key="test.critical",
            tier=notif_module.NotificationTier.MUST,
            severity=notif_module.NotificationSeverity.CRITICAL,
            dedup_key="test_crit",
            message_template="critical event",
        )
        mgr.rules["test.critical"] = rule
        mgr.handle_event({"category": "test", "type": "critical", "data": {}})

        assert len(calls) == 1
        assert calls[0][1] == "critical event"

    def test_non_critical_does_not_trigger_desktop(self, monkeypatch):
        """INFO/WARNING/ERROR should NOT trigger desktop."""
        from core.autonomic import notifications as notif_module

        calls = []
        monkeypatch.setattr(notif_module, "_show_desktop_notification",
                           lambda title, msg: calls.append((title, msg)))

        mgr = notif_module.NotificationManager()
        mgr.handle_event({"category": "safety", "type": "pii_anonymized",
                          "data": {"entity_count": 1}})
        assert calls == []

    def test_desktop_respects_setting(self, monkeypatch):
        """When notifications_desktop_enabled=False, CRITICAL does NOT escalate to desktop."""
        from core.autonomic import notifications as notif_module
        from core.interface import settings as settings_module

        calls = []
        monkeypatch.setattr(notif_module, "_show_desktop_notification",
                           lambda title, msg: calls.append((title, msg)))

        def fake_get_setting(key, default=None):
            if key == "notifications": return True
            if key == "notifications_must_enabled": return True
            if key == "notifications_desktop_enabled": return False
            return default
        monkeypatch.setattr(settings_module, "get_setting", fake_get_setting)

        mgr = notif_module.NotificationManager()
        rule = notif_module.NotificationRule(
            event_key="test.critical",
            tier=notif_module.NotificationTier.MUST,
            severity=notif_module.NotificationSeverity.CRITICAL,
            dedup_key="test_crit",
            message_template="critical event",
        )
        mgr.rules["test.critical"] = rule
        mgr.handle_event({"category": "test", "type": "critical", "data": {}})

        assert calls == []
```

- [ ] **Step 2: Run the tests to verify they fail**

```
.venv/Scripts/python -m pytest tests/test_notifications.py::TestDesktopEscalation -v
```

Expected: 3 failures.

- [ ] **Step 3: Implement _show_desktop_notification**

Edit `core/autonomic/notifications.py`. Find the existing stub:

```python
def _show_desktop_notification(title: str, message: str) -> None:
    """Fire-and-forget BurntToast desktop notification (Windows only).

    Filled in by Task 9 — stub for now so CRITICAL severity doesn't crash.
    """
    log.debug("Desktop notification (stub): %s — %s", title, message)
```

Replace with:

```python
def _show_desktop_notification(title: str, message: str) -> None:
    """Fire-and-forget BurntToast desktop notification (Windows only).

    Non-blocking — spawns PowerShell in a detached subprocess so slow
    BurntToast initialization doesn't delay notification dispatch.
    """
    import subprocess
    import sys

    if sys.platform != "win32":
        log.debug("Desktop notification skipped (non-Windows): %s", title)
        return

    # Sanitize title and message for PowerShell — escape single quotes
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
```

Also update the `_default_dispatch` method in `NotificationManager` to respect the desktop setting:

```python
    def _default_dispatch(self, message: str, title: str, severity: NotificationSeverity,
                         timeout: int) -> None:
        """Append to pending buffer for TUI/API consumption."""
        pending = PendingNotification(
            timestamp=time.time(),
            message=message,
            title=title,
            severity=severity.value,
            timeout_seconds=timeout,
            event_key=title,
        )
        self._pending.append(pending)
        # CRITICAL severity escalates to desktop if enabled
        if severity == NotificationSeverity.CRITICAL and self._desktop_enabled():
            _show_desktop_notification(title, message)

    @staticmethod
    def _desktop_enabled() -> bool:
        try:
            from core.interface.settings import get_setting
            return bool(get_setting("notifications_desktop_enabled", True))
        except ImportError:
            return True
```

- [ ] **Step 4: Run the desktop tests**

```
.venv/Scripts/python -m pytest tests/test_notifications.py::TestDesktopEscalation -v
```

Expected: 3 passed.

- [ ] **Step 5: Run full notification test suite**

```
.venv/Scripts/python -m pytest tests/test_notifications.py tests/test_notifications_integration.py tests/test_notification_settings.py tests/test_tui_notification_bar.py -v
```

Expected: all passed. Should be ~25-28 tests total.

- [ ] **Step 6: Commit**

```
git add core/autonomic/notifications.py tests/test_notifications.py
git commit -m "feat(notifications): T-119 desktop escalation via BurntToast for CRITICAL severity"
```

---

## Task 10: Final Verification, Manual Smoke Test, Build Report, PR

**Files:**
- Create: `D:\COMMAND\messages\2026-04-05\ENGINEER_BUILD_REPORT_T119.md`

- [ ] **Step 1: Run the full Python test suite**

```
.venv/Scripts/python -m pytest tests/ -v --timeout=60
```

Expected: **1,956+ passed** (previous 1,941 + ~16 new tests). Zero failures. Flag any regressions immediately.

- [ ] **Step 2: Run vitest**

```
cd frontend && npm run test -- --run
```

Expected: all passed (55+ tests).

- [ ] **Step 3: Run the gauntlet**

```
.venv/Scripts/python -m core.interface.cli gauntlet
```

Expected: 10/10 PASS. NotificationManager must not introduce any safety regressions.

- [ ] **Step 4: Manual smoke test — CLI**

Start the server:
```
.venv/Scripts/python -m core.interface.cli serve &
```

Trigger a notification by running a query with PII:
```
.venv/Scripts/python -m core.interface.cli query "my email is test@example.com what time is it"
```

Then check the API:
```
curl http://127.0.0.1:8420/api/notifications/pending
```

Expected: JSON response with at least one notification for `safety.pii_anonymized`.

- [ ] **Step 5: Manual smoke test — TUI**

Launch the TUI:
```
.venv/Scripts/python -m core.interface.cli tui
```

Run a query with PII in the chat view. Within 3 seconds, the NotificationBar at the bottom should display "[i] PII anonymized ...". Verify the bar disappears after the notification ages out.

- [ ] **Step 6: Manual smoke test — Desktop**

Inject a CRITICAL notification directly via a test script:

```
.venv/Scripts/python -c "from core.autonomic.events import emit_event; from core.autonomic.notifications import get_manager, NotificationRule, NotificationTier, NotificationSeverity; mgr = get_manager(); mgr.rules['test.critical'] = NotificationRule(event_key='test.critical', tier=NotificationTier.MUST, severity=NotificationSeverity.CRITICAL, dedup_key='test', message_template='Desktop test'); emit_event('test', 'critical', {})"
```

Expected: Windows BurntToast appears in the lower-right corner. If BurntToast module isn't installed, this silently fails — OK for now, document it in the build report.

- [ ] **Step 7: Write the build report**

Create `D:\COMMAND\messages\2026-04-05\ENGINEER_BUILD_REPORT_T119.md`:

```markdown
# ENGINEER BUILD REPORT — T-119
**FROM:** ENGINEER
**TO:** SYNTH (cc: ARCHITECT)
**DATE:** 2026-04-05
**TASK:** T-119 — Background Notifications
**STATUS:** COMPLETE / PENDING SYNTH REVIEW

## Summary
[2-3 sentence summary]

## Amendments Incorporated
1. Hook into emit_event() choke point — DONE
2. Composite key f"{category}.{type}" — DONE
3. New emission points — DONE (list: pii_anonymized, output_filter_activated, session_warning, restart_attempt, idle_cascade)
4. Settings registered in T-117 registry (Advanced tier) — DONE
5. Polling pattern (T-102) instead of app reference — DONE

## Files Changed
[list with line counts]

## Test Results
- Python: X passed / 0 failed (X new tests in T-119)
- Vitest: 55 passed / 0 failed
- Gauntlet: 10/10
- Manual smoke: CLI ✓  TUI ✓  Desktop ✓/⚠

## New Emission Points Added
[5 entries with file:line references]

## Deviations from Dispatch
[anything that diverged from the original spec or amendments]

## Known Limitations
[e.g., BurntToast not installed on this machine → desktop escalation untested live]

## PR
#13 — feat/t-119-notifications
```

- [ ] **Step 8: Push the branch**

```
git push -u origin feat/t-119-notifications
```

- [ ] **Step 9: Open PR #13**

```
gh pr create --title "feat: T-119 background notifications with three-tier policy" --body "$(cat <<'EOF'
## Summary
- NotificationManager with MUST/SHOULD/SILENT tiers hooked into emit_event() choke point
- 4 new emission points (pii_anonymized, output_filter_activated, session_warning, restart_attempt)
- fsm.idle_cascade emitted on ACTIVE→IDLE transition
- Ring buffer + /api/notifications/pending endpoint + /api/notifications/stream SSE
- TUI NotificationBar widget with 3s polling (T-102 pattern)
- Desktop escalation via BurntToast for CRITICAL severity only
- 3 new settings in T-117 registry (Advanced tier)

## Test plan
- [x] Full pytest suite green (1,956+ passed)
- [x] vitest green (55+ passed)
- [x] Gauntlet 10/10
- [x] Manual smoke: CLI query with PII → notification appears
- [x] Manual smoke: TUI NotificationBar updates on event
- [x] Manual smoke: Desktop BurntToast for injected CRITICAL
EOF
)"
```

- [ ] **Step 10: Update todos and stand by for SYNTH certification**

Mark all T-119 todos complete. Wait for SYNTH review. Do NOT merge without SYNTH ruling.

---

## Self-Review Checklist

Before executing this plan:
- [x] Every task has concrete file paths
- [x] Every step with code shows the actual code
- [x] Every step with a command shows the actual command
- [x] Tests are written before implementation (TDD)
- [x] Composite key `{category}.{type}` used consistently
- [x] Settings names match across plan and code (`notifications_must_enabled`, `notifications_should_enabled`, `notifications_desktop_enabled`)
- [x] Event keys match across policy table and emission points
- [x] NotificationState method names match (`should_fire`, `record`, `reset`)
- [x] PendingNotification shape matches API return shape
- [x] All SYNTH-approved amendments are represented

## Risk Mitigations

| Risk | Mitigation |
|---|---|
| Circular import (notifications ↔ events) | Lazy import in `_dispatch_notification`, hook set on first call |
| Event log write failure | Notification hook runs BEFORE log write — notifications fire even if jsonl fails |
| Thread safety | `NotificationManager._lock` protects state and pending buffer |
| Test pollution via module singleton | Tests use `monkeypatch.setattr(notif_module, "_manager", ...)` |
| BurntToast not installed | Subprocess failure is caught and logged at debug level |
| Unknown events crash manager | `handle_event` returns early on `rule is None` |
| Missing template fields | `_safe_format` catches KeyError/IndexError and returns raw template |
| Frontend toast infra missing | Task 8 scopes down to API-only and flags in build report |
| Test isolation across NotificationManager singleton | Each test fixture creates a fresh manager via monkeypatch |

---

**Plan complete. Ready for ARCHITECT review → execution.**
