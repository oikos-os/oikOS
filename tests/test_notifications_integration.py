"""Integration tests for NotificationManager hooked into emit_event()."""
from __future__ import annotations

import pytest

from core.autonomic import events as events_module
from core.autonomic.notifications import NotificationManager, NotificationSeverity


@pytest.fixture
def clean_manager(monkeypatch, tmp_path):
    """Fresh NotificationManager + temp events.jsonl for each test.

    Explicitly resets events_module._notification_hook and the singleton
    NotificationManager before AND after the test — do not rely on monkeypatch
    revert semantics, which restore the previous value (possibly a real-singleton
    lambda from a prior test that already triggered lazy init).
    """
    from core.autonomic.notifications import reset_manager

    # Pre-test: ensure clean slate regardless of prior test state
    events_module._notification_hook = None
    reset_manager()

    mgr = NotificationManager()
    captured: list[tuple] = []
    mgr._dispatch_fn = lambda msg, title, sev, timeout, key: captured.append((msg, title, sev, timeout, key))

    # Point events.jsonl at a temp file so we don't pollute real logs
    monkeypatch.setattr(events_module, "EVENTS_LOG", tmp_path / "events.jsonl")
    # Inject the test manager via the hook
    monkeypatch.setattr(events_module, "_notification_hook",
                        lambda record: mgr.handle_event(record))

    yield mgr, captured

    # Post-test: explicit cleanup so later tests in the suite start clean
    events_module._notification_hook = None
    reset_manager()


class TestEmitEventHook:
    def test_pii_event_triggers_notification(self, clean_manager):
        mgr, captured = clean_manager
        events_module.emit_event("safety", "pii_anonymized", {"entity_count": 2})
        assert len(captured) == 1
        msg, title, sev, timeout, key = captured[0]
        assert "2 entities" in msg
        assert sev == NotificationSeverity.INFO
        assert key == "safety.pii_anonymized"

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

    def test_notification_fires_even_when_log_write_fails(self, clean_manager, monkeypatch, tmp_path):
        """If the jsonl write fails, notifications should still fire because the
        hook runs BEFORE the log write."""
        mgr, captured = clean_manager

        # Make the log write raise OSError only for events.jsonl
        real_open = open
        def conditional_open(path, *args, **kwargs):
            if str(path).endswith("events.jsonl"):
                raise OSError("disk full")
            return real_open(path, *args, **kwargs)
        monkeypatch.setattr("builtins.open", conditional_open)

        # Should not raise and notification should still fire
        events_module.emit_event("safety", "pii_anonymized", {"entity_count": 1})
        assert len(captured) == 1
        assert "PII anonymized" in captured[0][0]

    def test_hook_runs_before_log_write(self, monkeypatch, tmp_path):
        """Pin the ordering: hook must fire BEFORE the log write.

        Uses a side-channel order list recorded by both the hook and the
        file-open wrapper. The sequence must be ["hook", "write"], not
        ["write", "hook"] — that ordering is what guarantees the notification
        survives a disk failure.
        """
        monkeypatch.setattr(events_module, "EVENTS_LOG", tmp_path / "events.jsonl")
        order: list[str] = []
        monkeypatch.setattr(events_module, "_notification_hook",
                            lambda r: order.append("hook"))
        real_open = open
        def tracked_open(path, *args, **kwargs):
            if str(path).endswith("events.jsonl"):
                order.append("write")
            return real_open(path, *args, **kwargs)
        monkeypatch.setattr("builtins.open", tracked_open)

        events_module.emit_event("safety", "pii_anonymized", {"entity_count": 1})
        assert order == ["hook", "write"], f"wrong order: {order}"

    def test_hook_exception_does_not_crash_emit_event(self, monkeypatch, tmp_path):
        """A hook that raises at call time must not crash emit_event.

        The outer try/except in _dispatch_notification swallows the exception
        at debug level. The log write must still succeed.
        """
        monkeypatch.setattr(events_module, "EVENTS_LOG", tmp_path / "events.jsonl")

        def broken_hook(record):
            raise RuntimeError("simulated hook failure")
        monkeypatch.setattr(events_module, "_notification_hook", broken_hook)

        # Should not raise
        events_module.emit_event("safety", "pii_anonymized", {"entity_count": 1})

        # And the log write should still succeed
        log_file = tmp_path / "events.jsonl"
        assert log_file.exists()
        assert "pii_anonymized" in log_file.read_text(encoding="utf-8")


class TestPipelineEmission:
    """Tests that verify the pipeline emits safety events at the right points."""

    def test_pii_scrub_emits_event(self, clean_manager):
        """classify_input should emit safety.pii_anonymized when PII is scrubbed."""
        from unittest.mock import patch, MagicMock
        from core.cognition.pipeline.classify import classify_input
        from core.interface.models import PIIResult

        mgr, captured = clean_manager

        from core.interface.models import PIIEntity
        # Build a fake PII detection result with 2 entities
        fake_pii = PIIResult(has_pii=True, entities=[
            PIIEntity(entity_type="email", text="foo@bar.com", start=12, end=23, score=0.99),
            PIIEntity(entity_type="phone", text="555-1234", start=30, end=38, score=0.95),
        ])
        fake_scrub = MagicMock()
        fake_scrub.scrubbed_text = "my email is [REDACTED] phone [REDACTED]"

        with patch("core.cognition.pipeline.classify.detect_pii", return_value=fake_pii), \
             patch("core.cognition.pipeline.classify.scrub_pii", return_value=fake_scrub), \
             patch("core.cognition.pipeline.classify.log_detection"):
            classify_input("my email is foo@bar.com phone 555-1234", "hash123")

        # Expect a notification for pii_anonymized
        assert any("PII anonymized" in msg for msg, _, _, _, _ in captured), \
            f"expected PII notification, got: {captured}"
        # Verify it's the right event_key
        keys = [key for _, _, _, _, key in captured]
        assert "safety.pii_anonymized" in keys

    def test_pii_not_scrubbed_does_not_emit(self, clean_manager):
        """classify_input should NOT emit pii_anonymized if no PII is detected."""
        from unittest.mock import patch
        from core.cognition.pipeline.classify import classify_input
        from core.interface.models import PIIResult

        mgr, captured = clean_manager

        fake_pii = PIIResult(has_pii=False, entities=[])
        with patch("core.cognition.pipeline.classify.detect_pii", return_value=fake_pii):
            classify_input("a perfectly clean query", "hash456")

        # No PII notification expected
        pii_events = [k for _, _, _, _, k in captured if k == "safety.pii_anonymized"]
        assert pii_events == []

    def test_output_filter_emits_event(self, clean_manager):
        """post_process should emit safety.output_filter_activated when filter fires."""
        from unittest.mock import patch, MagicMock
        from core.cognition.pipeline.postprocess import post_process
        from core.interface.models import ConfidenceResult

        mgr, captured = clean_manager

        # Build a fake filter result indicating MEDIUM sensitivity
        fake_filter = MagicMock()
        fake_filter.level = "MEDIUM"
        fake_filter.triggered = ["keyword_foo"]
        fake_filter.response = "filtered text"

        # Build a minimal PreparedContext stub that post_process expects
        fake_decision = MagicMock()
        fake_decision.reason = ""
        fake_decision.cosine_gate_fired = False
        fake_ctx = MagicMock()
        fake_ctx.effective_query = "test"
        fake_ctx.session = {"session_id": "s1"}
        fake_ctx.decision = fake_decision

        fake_assertion = MagicMock()
        fake_assertion.contains_assertion = False

        fake_coherence = MagicMock()
        fake_coherence.is_coherent = True

        with patch("core.safety.output_filter.check_output_sensitivity", return_value=fake_filter), \
             patch("core.autonomic.confidence.score_response",
                   return_value=ConfidenceResult(score=0.8, method="test")), \
             patch("core.identity.coherence.check_coherence", return_value=fake_coherence), \
             patch("core.identity.assertions.check_assertion", return_value=fake_assertion):
            post_process("response text", None, fake_ctx, "test-model")

        # Expect a notification for output_filter_activated
        assert any("Output filtered" in msg for msg, _, _, _, _ in captured), \
            f"expected output filter notification, got: {captured}"
        keys = [key for _, _, _, _, key in captured]
        assert "safety.output_filter_activated" in keys

    def test_output_filter_clean_does_not_emit(self, clean_manager):
        """post_process should NOT emit when filter result is CLEAN."""
        from unittest.mock import patch, MagicMock
        from core.cognition.pipeline.postprocess import post_process
        from core.interface.models import ConfidenceResult

        mgr, captured = clean_manager

        fake_filter = MagicMock()
        fake_filter.level = "CLEAN"
        fake_filter.triggered = []
        fake_filter.response = "clean text"

        fake_decision = MagicMock()
        fake_decision.reason = ""
        fake_decision.cosine_gate_fired = False
        fake_ctx = MagicMock()
        fake_ctx.effective_query = "test"
        fake_ctx.session = {"session_id": "s1"}
        fake_ctx.decision = fake_decision

        fake_assertion = MagicMock()
        fake_assertion.contains_assertion = False
        fake_coherence = MagicMock()
        fake_coherence.is_coherent = True

        with patch("core.safety.output_filter.check_output_sensitivity", return_value=fake_filter), \
             patch("core.autonomic.confidence.score_response",
                   return_value=ConfidenceResult(score=0.8, method="test")), \
             patch("core.identity.coherence.check_coherence", return_value=fake_coherence), \
             patch("core.identity.assertions.check_assertion", return_value=fake_assertion):
            post_process("response text", None, fake_ctx, "test-model")

        filter_events = [k for _, _, _, _, k in captured if k == "safety.output_filter_activated"]
        assert filter_events == []


class TestDaemonFSMEmission:
    """Tests for Task 4 emission points — session_warning, restart_attempt, idle_cascade."""

    def test_restart_attempt_emits_event(self, clean_manager, monkeypatch):
        """_attempt_restart should emit inference.restart_attempt with attempt + backend."""
        import asyncio
        from core.autonomic import daemon

        mgr, captured = clean_manager

        # Build a stub inference manager that exposes backend_name + a no-op restart
        class StubManager:
            def backend_name(self):
                return "Ollama"
            async def restart(self):
                return True

        monkeypatch.setattr(daemon, "_inference_manager", StubManager())
        monkeypatch.setattr(daemon, "_restart_attempts", 0)
        monkeypatch.setattr(daemon, "_restart_window_start", None)
        # Skip the real sleep — don't wait through the backoff in tests
        monkeypatch.setattr(daemon.time, "sleep", lambda _: None)

        daemon._attempt_restart()

        # Expect a SHOULD-tier notification for the first attempt
        keys = [k for _, _, _, _, k in captured]
        assert "inference.restart_attempt" in keys, f"captured keys: {keys}"

    def test_restart_attempt_escalates_on_third_call(self, clean_manager, monkeypatch):
        """Third restart attempt should fire the escalated 'exhausted' notification."""
        import asyncio
        from core.autonomic import daemon
        from core.autonomic.notifications import NotificationSeverity

        mgr, captured = clean_manager

        class StubManager:
            def backend_name(self):
                return "Ollama"
            async def restart(self):
                return False  # fail each time

        monkeypatch.setattr(daemon, "_inference_manager", StubManager())
        monkeypatch.setattr(daemon, "_restart_attempts", 0)
        monkeypatch.setattr(daemon, "_restart_window_start", None)
        monkeypatch.setattr(daemon.time, "sleep", lambda _: None)

        # Fire three restart attempts back-to-back
        for _ in range(3):
            daemon._attempt_restart()

        # With threshold=2 (Task 1 fix): attempt 1 fires WARNING, attempt 2 suppressed, attempt 3 fires ERROR
        restart_events = [(msg, sev) for msg, _, sev, _, k in captured if k == "inference.restart_attempt"]
        assert len(restart_events) == 2, f"expected 2 restart events, got: {restart_events}"
        msg1, sev1 = restart_events[0]
        msg2, sev2 = restart_events[1]
        assert sev1 == NotificationSeverity.WARNING
        assert sev2 == NotificationSeverity.ERROR
        assert "exhausted" in msg2.lower() or "cloud fallback" in msg2.lower()

    def test_session_warning_emits_before_stale(self, clean_manager, monkeypatch):
        """_check_stale_sessions should emit daemon.session_warning 5 min before auto-close."""
        from datetime import datetime, timedelta, timezone
        from core.autonomic import daemon

        mgr, captured = clean_manager

        # Reset session warning state — keyed on session_id, not a bare bool
        monkeypatch.setattr(daemon, "_session_warning_session_id", None)
        monkeypatch.setattr(daemon, "_last_session_check", 0.0)

        stale_min = daemon.DAEMON_SESSION_STALE_MINUTES
        # Set last_active so that elapsed is inside the warning window but not yet stale
        warning_elapsed = stale_min - 4  # 4 minutes before close → inside warning window
        fake_last_active = datetime.now(timezone.utc) - timedelta(minutes=warning_elapsed)
        fake_state = {"last_active_at": fake_last_active.isoformat(), "session_id": "test-session"}

        import core.memory.session as session_module
        monkeypatch.setattr(session_module, "_load_state", lambda: fake_state)
        # Prevent actual close — we only want the warning to fire
        monkeypatch.setattr(session_module, "close_session", lambda: None)

        daemon._check_stale_sessions()

        keys = [k for _, _, _, _, k in captured]
        assert "daemon.session_warning" in keys, f"captured keys: {keys}"

    def test_session_warning_does_not_fire_when_fresh(self, clean_manager, monkeypatch):
        """If session is fresh (elapsed < warning threshold), no warning should fire."""
        from datetime import datetime, timedelta, timezone
        from core.autonomic import daemon

        mgr, captured = clean_manager

        monkeypatch.setattr(daemon, "_session_warning_session_id", None)
        monkeypatch.setattr(daemon, "_last_session_check", 0.0)

        # Very recent activity — 1 minute ago
        fake_last_active = datetime.now(timezone.utc) - timedelta(minutes=1)
        fake_state = {"last_active_at": fake_last_active.isoformat(), "session_id": "fresh"}

        import core.memory.session as session_module
        monkeypatch.setattr(session_module, "_load_state", lambda: fake_state)
        monkeypatch.setattr(session_module, "close_session", lambda: None)

        daemon._check_stale_sessions()

        keys = [k for _, _, _, _, k in captured]
        assert "daemon.session_warning" not in keys

    def test_fsm_transition_to_idle_emits_idle_cascade(self, clean_manager, monkeypatch, tmp_path):
        """FSM ACTIVE→IDLE transition should emit fsm.idle_cascade alongside fsm.transition."""
        from core.autonomic import fsm
        from core.interface.models import SystemState

        mgr, captured = clean_manager

        # Redirect state file to temp location so we don't mutate real fsm state
        monkeypatch.setattr(fsm, "FSM_STATE_FILE", tmp_path / "fsm_state.json")
        monkeypatch.setattr(fsm, "FSM_TRANSITION_LOG", tmp_path / "fsm_transitions.jsonl")
        # Force get_current_state to return ACTIVE (the default when file missing)
        monkeypatch.setattr(fsm, "get_current_state", lambda: SystemState.ACTIVE)

        # Stub out _on_enter_idle callback to skip its heavy side effects (indexing, etc.)
        monkeypatch.setattr(fsm, "_on_enter_idle", lambda: {"stubbed": True})

        fsm.transition_to(SystemState.IDLE, trigger="test_idle_cascade")

        keys = [k for _, _, _, _, k in captured]
        assert "fsm.idle_cascade" in keys, f"captured keys: {keys}"

    def test_fsm_transition_to_active_does_not_emit_idle_cascade(self, clean_manager, monkeypatch, tmp_path):
        """Non-IDLE transitions should NOT emit idle_cascade."""
        from core.autonomic import fsm
        from core.interface.models import SystemState

        mgr, captured = clean_manager

        monkeypatch.setattr(fsm, "FSM_STATE_FILE", tmp_path / "fsm_state.json")
        monkeypatch.setattr(fsm, "FSM_TRANSITION_LOG", tmp_path / "fsm_transitions.jsonl")
        monkeypatch.setattr(fsm, "get_current_state", lambda: SystemState.IDLE)
        monkeypatch.setattr(fsm, "_on_enter_active", lambda: {"stubbed": True})

        fsm.transition_to(SystemState.ACTIVE, trigger="test_wake")

        keys = [k for _, _, _, _, k in captured]
        assert "fsm.idle_cascade" not in keys


class TestNotificationAPI:
    """Tests for GET /api/notifications/pending endpoint."""

    def test_get_pending_returns_empty_initially(self, monkeypatch):
        from fastapi.testclient import TestClient
        from core.autonomic import notifications as notif_module
        from core.autonomic import events as events_module
        from core.interface.api.server import build_app

        # Fresh manager + clean hook for isolation
        notif_module.reset_manager()
        events_module._notification_hook = None
        fresh_mgr = notif_module.NotificationManager()
        monkeypatch.setattr(notif_module, "_manager", fresh_mgr)
        monkeypatch.setattr(events_module, "_notification_hook",
                           lambda r: fresh_mgr.handle_event(r))

        try:
            app = build_app()
            with TestClient(app) as client:
                r = client.get("/api/notifications/pending")
                assert r.status_code == 200
                assert r.json() == {"pending": []}
        finally:
            notif_module.reset_manager()
            events_module._notification_hook = None

    def test_get_pending_returns_fired_notifications(self, monkeypatch):
        from fastapi.testclient import TestClient
        from core.autonomic import notifications as notif_module
        from core.autonomic import events as events_module
        from core.interface.api.server import build_app

        notif_module.reset_manager()
        events_module._notification_hook = None
        fresh_mgr = notif_module.NotificationManager()
        monkeypatch.setattr(notif_module, "_manager", fresh_mgr)
        monkeypatch.setattr(events_module, "_notification_hook",
                           lambda r: fresh_mgr.handle_event(r))

        try:
            # Fire a real emission through the hook
            events_module.emit_event("safety", "pii_anonymized", {"entity_count": 1})

            app = build_app()
            with TestClient(app) as client:
                r = client.get("/api/notifications/pending")
                assert r.status_code == 200
                body = r.json()
                assert "pending" in body
                assert len(body["pending"]) == 1
                item = body["pending"][0]
                assert "PII anonymized" in item["message"]
                assert item["severity"] == "information"
                assert item["event_key"] == "safety.pii_anonymized"
                assert item["title"] == "PII Scrubbed"
                assert "timestamp" in item
                assert "timeout_seconds" in item
        finally:
            notif_module.reset_manager()
            events_module._notification_hook = None

    def test_get_pending_filters_by_since_timestamp(self, monkeypatch):
        """?since=<timestamp> returns only newer notifications."""
        import time
        from fastapi.testclient import TestClient
        from core.autonomic import notifications as notif_module
        from core.autonomic import events as events_module
        from core.interface.api.server import build_app

        notif_module.reset_manager()
        events_module._notification_hook = None
        fresh_mgr = notif_module.NotificationManager()
        monkeypatch.setattr(notif_module, "_manager", fresh_mgr)
        monkeypatch.setattr(events_module, "_notification_hook",
                           lambda r: fresh_mgr.handle_event(r))

        try:
            events_module.emit_event("safety", "pii_anonymized", {"entity_count": 1})
            time.sleep(0.02)
            cutoff = time.time()
            time.sleep(0.02)
            events_module.emit_event("daemon", "budget_critical", {"usage_percent": 95})

            app = build_app()
            with TestClient(app) as client:
                r = client.get(f"/api/notifications/pending?since={cutoff}")
                assert r.status_code == 200
                body = r.json()
                assert len(body["pending"]) == 1
                assert "budget" in body["pending"][0]["message"].lower()
        finally:
            notif_module.reset_manager()
            events_module._notification_hook = None

    def test_post_reset_clears_state(self, monkeypatch):
        from fastapi.testclient import TestClient
        from core.autonomic import notifications as notif_module
        from core.autonomic import events as events_module
        from core.interface.api.server import build_app

        notif_module.reset_manager()
        events_module._notification_hook = None
        fresh_mgr = notif_module.NotificationManager()
        monkeypatch.setattr(notif_module, "_manager", fresh_mgr)
        monkeypatch.setattr(events_module, "_notification_hook",
                           lambda r: fresh_mgr.handle_event(r))

        try:
            # Fire some events
            events_module.emit_event("safety", "pii_anonymized", {"entity_count": 1})
            events_module.emit_event("daemon", "budget_critical", {"usage_percent": 95})

            app = build_app()
            with TestClient(app) as client:
                # Confirm there are notifications
                r = client.get("/api/notifications/pending")
                assert len(r.json()["pending"]) == 2

                # Reset
                r = client.post("/api/notifications/reset")
                assert r.status_code == 200
                assert r.json() == {"status": "reset"}

                # Now empty
                r = client.get("/api/notifications/pending")
                assert r.json() == {"pending": []}
        finally:
            notif_module.reset_manager()
            events_module._notification_hook = None
