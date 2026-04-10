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
        mgr._dispatch_fn = lambda msg, title, sev, timeout, key: dispatched.append(msg)
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
        mgr._dispatch_fn = lambda msg, title, sev, timeout, key: captured.append(msg)
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
        mgr._dispatch_fn = lambda msg, title, sev, timeout, key: captured.append((msg, sev))
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
        mgr._dispatch_fn = lambda msg, title, sev, timeout, key: captured.append((msg, sev))
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
        mgr._dispatch_fn = lambda msg, title, sev, timeout, key: captured.append(msg)
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
        mgr._dispatch_fn = lambda msg, title, sev, timeout, key: captured.append(msg)
        # Missing field should not crash — use raw template or placeholder
        mgr.handle_event({"category": "test", "type": "event", "data": {}})
        assert len(captured) == 1  # did not crash

    def test_restart_attempt_escalates_on_third_attempt(self):
        """Simulate the real 3-attempt restart loop — user should see 2 notifications total."""
        mgr = NotificationManager()
        mgr.rules = _build_default_rules()  # Use real policy table
        captured = []
        mgr._dispatch_fn = lambda msg, title, sev, timeout, key: captured.append((msg, sev))

        # Simulate 3 restart attempts from daemon._attempt_restart
        for attempt in (1, 2, 3):
            mgr.handle_event({
                "category": "inference",
                "type": "restart_attempt",
                "data": {"attempt": attempt, "max_attempts": 3, "backend": "Ollama"},
            })

        # With threshold=2: attempt 1 fires (count 0→1), attempt 2 suppressed (count 1→2),
        # attempt 3 fires as ESCALATED (count 2→3, 2>=2 is True)
        assert len(captured) == 2, f"expected 2 notifications, got {len(captured)}: {captured}"
        msg1, sev1 = captured[0]
        msg2, sev2 = captured[1]
        assert "restart 1/3" in msg1
        assert sev1 == NotificationSeverity.WARNING
        assert "exhausted" in msg2
        assert sev2 == NotificationSeverity.ERROR

    def test_pending_notification_event_key_is_composite_key(self):
        """event_key field of PendingNotification must hold '{category}.{type}', not title."""
        mgr = NotificationManager()
        # Use the real default policy so we have a titled rule
        mgr.handle_event({
            "category": "safety",
            "type": "pii_anonymized",
            "data": {"entity_count": 1},
        })
        pending = mgr.drain_pending()
        assert len(pending) == 1
        assert pending[0]["event_key"] == "safety.pii_anonymized"
        assert pending[0]["title"] == "PII Scrubbed"  # title is separate


class TestNotificationManagerDispatch:
    """Tests for the default dispatch path — ring buffer, drain, reset, singleton."""

    def test_drain_pending_returns_all_buffered_when_no_filter(self):
        mgr = NotificationManager()
        mgr.handle_event({"category": "safety", "type": "pii_anonymized", "data": {"entity_count": 1}})
        mgr.handle_event({"category": "daemon", "type": "budget_critical", "data": {"usage_percent": 95}})
        pending = mgr.drain_pending()
        assert len(pending) == 2
        assert pending[0]["message"].startswith("PII anonymized")
        assert pending[1]["message"].startswith("Monthly budget")

    def test_drain_pending_filters_by_since_timestamp(self):
        import time as _time
        mgr = NotificationManager()
        mgr.handle_event({"category": "safety", "type": "pii_anonymized", "data": {"entity_count": 1}})
        cutoff = _time.time()
        _time.sleep(0.01)
        mgr.handle_event({"category": "daemon", "type": "budget_critical", "data": {"usage_percent": 95}})
        pending = mgr.drain_pending(since_timestamp=cutoff)
        assert len(pending) == 1
        assert "budget" in pending[0]["message"].lower()

    def test_ring_buffer_evicts_oldest_when_at_max(self):
        mgr = NotificationManager(max_pending=3)
        for i in range(5):
            mgr.handle_event({
                "category": "safety",
                "type": "pii_anonymized",
                "data": {"entity_count": i},
            })
        pending = mgr.drain_pending()
        # Only the last 3 should remain (deque maxlen=3)
        assert len(pending) == 3
        # Oldest two (entity_count=0, 1) evicted; 2, 3, 4 remain
        entity_counts = [int(n["message"].split("(")[1].split(" ")[0]) for n in pending]
        assert entity_counts == [2, 3, 4]

    def test_reset_session_clears_state_and_pending(self):
        mgr = NotificationManager()
        mgr.handle_event({"category": "safety", "type": "pii_anonymized", "data": {"entity_count": 1}})
        assert len(mgr.drain_pending()) == 1
        assert len(mgr.state.fired_keys) > 0

        mgr.reset_session()

        assert mgr.drain_pending() == []
        assert mgr.state.fired_keys == {}

    def test_get_manager_returns_singleton(self):
        from core.autonomic.notifications import get_manager, reset_manager
        reset_manager()  # ensure clean slate
        mgr1 = get_manager()
        mgr2 = get_manager()
        assert mgr1 is mgr2
        reset_manager()  # leave clean for other tests


class TestDesktopEscalation:
    """T-119 Task 9: Desktop BurntToast escalation for CRITICAL severity."""

    def test_critical_severity_triggers_desktop_call(self, monkeypatch):
        """CRITICAL severity should invoke the desktop notification helper."""
        from core.autonomic import notifications as notif_module

        calls = []
        monkeypatch.setattr(notif_module, "_show_desktop_notification",
                           lambda title, msg: calls.append((title, msg)))

        # Ensure settings allow desktop (default: True)
        from core.interface import settings as settings_module
        monkeypatch.setattr(settings_module, "get_setting",
                           lambda key: True)

        mgr = notif_module.NotificationManager()
        rule = notif_module.NotificationRule(
            event_key="test.critical",
            tier=notif_module.NotificationTier.MUST,
            severity=notif_module.NotificationSeverity.CRITICAL,
            dedup_key="test_crit",
            message_template="critical event",
            title="Critical Test",
        )
        mgr.rules["test.critical"] = rule
        mgr.handle_event({"category": "test", "type": "critical", "data": {}})

        assert len(calls) == 1
        assert calls[0][0] == "Critical Test"
        assert calls[0][1] == "critical event"

    def test_non_critical_does_not_trigger_desktop(self, monkeypatch):
        """INFO/WARNING/ERROR severity should NOT trigger desktop escalation."""
        from core.autonomic import notifications as notif_module

        calls = []
        monkeypatch.setattr(notif_module, "_show_desktop_notification",
                           lambda title, msg: calls.append((title, msg)))

        from core.interface import settings as settings_module
        monkeypatch.setattr(settings_module, "get_setting",
                           lambda key: True)

        mgr = notif_module.NotificationManager()
        # Default rule for pii_anonymized is MUST/INFO — should NOT escalate
        mgr.handle_event({"category": "safety", "type": "pii_anonymized",
                          "data": {"entity_count": 1}})

        assert calls == []

    def test_desktop_respects_setting(self, monkeypatch):
        """When notifications_desktop_enabled=False, CRITICAL should NOT call desktop."""
        from core.autonomic import notifications as notif_module
        from core.interface import settings as settings_module

        calls = []
        monkeypatch.setattr(notif_module, "_show_desktop_notification",
                           lambda title, msg: calls.append((title, msg)))

        def fake_get_setting(key):
            if key == "notifications":
                return True
            if key == "notifications_must_enabled":
                return True
            if key == "notifications_desktop_enabled":
                return False
            return True
        monkeypatch.setattr(settings_module, "get_setting", fake_get_setting)

        mgr = notif_module.NotificationManager()
        rule = notif_module.NotificationRule(
            event_key="test.critical",
            tier=notif_module.NotificationTier.MUST,
            severity=notif_module.NotificationSeverity.CRITICAL,
            dedup_key="test_crit2",
            message_template="critical event",
            title="Critical Test",
        )
        mgr.rules["test.critical"] = rule
        mgr.handle_event({"category": "test", "type": "critical", "data": {}})

        # The in-memory buffer still captures the event, but desktop is gated
        assert calls == [], "desktop call should be blocked when setting is False"

    def test_show_desktop_notification_non_blocking(self, monkeypatch):
        """The real _show_desktop_notification must not block on subprocess."""
        import sys
        from core.autonomic import notifications as notif_module

        # Only verify on Windows — non-Windows platforms return early
        if sys.platform != "win32":
            pytest.skip("Desktop notification is Windows-only")

        # Monkeypatch subprocess.Popen to verify it's called (not subprocess.run)
        calls = []
        import subprocess as real_subprocess

        class FakePopen:
            def __init__(self, *args, **kwargs):
                calls.append(("Popen", args, kwargs))

        monkeypatch.setattr("subprocess.Popen", FakePopen)

        notif_module._show_desktop_notification("Test Title", "Test Message")

        assert len(calls) == 1
        name, args, kwargs = calls[0]
        assert name == "Popen"
        # First argument should be a list starting with powershell.exe
        assert isinstance(args[0], list)
        assert "powershell" in args[0][0].lower()
        # CREATE_NO_WINDOW flag should be set (or at least creationflags kwarg present)
        assert "creationflags" in kwargs or "stdout" in kwargs
