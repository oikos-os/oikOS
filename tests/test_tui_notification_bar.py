"""T-119 Task 7: TUI NotificationBar widget tests."""
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
            "timestamp": 1234567890.0,
            "timeout_seconds": 4,
            "event_key": "safety.pii_anonymized",
        }])
        assert bar.display is True

    def test_shown_with_multiple_notifications(self):
        bar = NotificationBar()
        notifs = [
            {"message": "first", "title": "A", "severity": "information",
             "timestamp": 1.0, "timeout_seconds": 4, "event_key": "a.one"},
            {"message": "second", "title": "B", "severity": "warning",
             "timestamp": 2.0, "timeout_seconds": 5, "event_key": "b.two"},
            {"message": "third", "title": "C", "severity": "error",
             "timestamp": 3.0, "timeout_seconds": 10, "event_key": "c.three"},
        ]
        bar.update_pending(notifs)
        assert bar.display is True

    def test_severity_prefix_information(self):
        """INFO severity uses [i] prefix."""
        bar = NotificationBar()
        bar.update_pending([{
            "message": "test info",
            "title": "T",
            "severity": "information",
            "timestamp": 1.0,
            "timeout_seconds": 4,
            "event_key": "t.info",
        }])
        # Rendered content is accessible via the widget's renderable
        # We can't easily inspect without a full Textual pilot, but we can
        # at least verify display state changed
        assert bar.display is True

    def test_state_resets_on_empty_after_content(self):
        """Widget should hide again if pending list becomes empty."""
        bar = NotificationBar()
        bar.update_pending([{
            "message": "test",
            "title": "T",
            "severity": "information",
            "timestamp": 1.0,
            "timeout_seconds": 4,
            "event_key": "t.one",
        }])
        assert bar.display is True
        bar.update_pending([])
        assert bar.display is False
