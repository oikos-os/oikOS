"""T-119: Background notification bar for the oikOS TUI.

Mirrors the T-102 ApprovalBar pattern. Docked above the footer.
Hidden when no notifications pending. Shows the most recent
notification plus a count if there are more than one.
"""
from __future__ import annotations

from textual.widgets import Static


# ASCII severity prefixes for terminal compatibility (no Unicode icons)
SEVERITY_PREFIX = {
    "information": "[i]",
    "warning": "[!]",
    "error": "[X]",
    "critical": "[!!]",
}


class NotificationBar(Static):
    """Transient notification bar for background events.

    Updated by the TUI app's polling method (3-second interval) based on
    GET /api/notifications/pending responses.
    """

    def __init__(self) -> None:
        super().__init__("", id="notification-bar")
        self._count = 0
        self._pending: list[dict] = []

    def update_pending(self, pending: list[dict]) -> None:
        """Update from list of pending notification dicts.

        Hides the widget if empty. Shows the newest notification (last in list,
        since the ring buffer appends chronologically) with a count suffix if
        more than one is pending.
        """
        self._count = len(pending)
        self._pending = pending
        if self._count == 0:
            self.display = False
            return

        self.display = True
        latest = pending[-1]
        message = latest.get("message", "")
        severity = latest.get("severity", "information")
        prefix = SEVERITY_PREFIX.get(severity, "[*]")

        if self._count == 1:
            self.update(f"{prefix} {message}")
        else:
            self.update(f"{prefix} {message}  (+{self._count - 1} more)")
