"""Approval notification bar — persistent amber alert for pending ASK_FIRST actions."""
from __future__ import annotations

from textual.widgets import Static


class ApprovalBar(Static):
    """Persistent notification bar shown when approval requests are pending.

    Docked above the footer. Hidden when no requests pending.
    """

    def __init__(self) -> None:
        super().__init__("", id="approval-bar")
        self._count = 0
        self._pending: list[dict] = []

    def update_pending(self, pending: list[dict]) -> None:
        """Update from list of pending approval dicts."""
        self._count = len(pending)
        self._pending = pending
        if self._count == 0:
            self.display = False
            return
        self.display = True
        first = pending[0]
        action = first.get("action", first.get("tool_name", "unknown"))
        if self._count == 1:
            self.update(f"\u26a0 ACTION PENDING: {action} [F9 to review]")
        else:
            self.update(
                f"\u26a0 {self._count} ACTIONS PENDING: {action} "
                f"(+{self._count - 1} more) [F9 to review]"
            )
