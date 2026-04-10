"""Approval modal — F9 screen for reviewing and acting on pending approvals."""
from __future__ import annotations

import logging
from datetime import datetime

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Static, ListView, ListItem

log = logging.getLogger(__name__)


class ApprovalModal(ModalScreen):
    """Modal screen showing pending approval requests."""

    BINDINGS = [
        Binding("enter", "approve_selected", "Approve"),
        Binding("escape", "dismiss", "Close"),
        Binding("r", "reject_selected", "Reject"),
    ]

    CSS = """
    ApprovalModal {
        align: center middle;
    }

    #approval-modal-container {
        width: 72;
        height: 22;
        background: #0A0A0A;
        border: tall #D4A017;
        padding: 1 2;
    }

    #approval-modal-title {
        color: #FFB000;
        text-style: bold;
        margin-bottom: 1;
    }

    #approval-detail {
        color: #D4A017;
        margin-top: 1;
    }

    #approval-keys {
        dock: bottom;
        height: 1;
        color: #6B5012;
    }

    .approval-item {
        color: #D4A017;
        height: 1;
    }
    """

    def __init__(self, pending: list[dict]) -> None:
        super().__init__()
        self._pending = pending
        self._selected_idx = 0

    def compose(self) -> ComposeResult:
        with Vertical(id="approval-modal-container"):
            yield Static("\u26a0 Pending Approvals", id="approval-modal-title")
            if not self._pending:
                yield Static("No pending approvals.", id="approval-detail")
            else:
                yield ListView(
                    *[ListItem(Static(self._format_item(p)), classes="approval-item")
                      for p in self._pending],
                    id="approval-list",
                )
                yield Static(self._format_detail(self._pending[0]), id="approval-detail")
            yield Static("Enter=Approve  R=Reject  Esc=Close", id="approval-keys")

    def _format_item(self, p: dict) -> str:
        """One-line summary for list."""
        tool = p.get("tool_name", "?")
        action = p.get("action", "")
        room = p.get("room", "") or "default"
        return f"\u25b8 {tool}  {action}  [{room}]"

    def _format_detail(self, p: dict) -> str:
        """Multi-line detail for selected approval."""
        lines = [
            f"Tool:    {p.get('tool_name', '?')}",
            f"Action:  {p.get('action', '?')}",
            f"Room:    {p.get('room', '') or 'default'}",
            f"Risk:    {p.get('risk_level', '?')}",
        ]
        args = p.get("arguments", {})
        for k, v in list(args.items())[:5]:
            val = str(v)[:60]
            lines.append(f"  {k}: {val}")
        expires = p.get("expires_at", "")
        if expires:
            try:
                exp_dt = datetime.fromisoformat(expires)
                now = datetime.now(exp_dt.tzinfo)
                remaining = int((exp_dt - now).total_seconds())
                if remaining > 0:
                    lines.append(f"Expires: {remaining}s remaining")
                else:
                    lines.append("Expires: EXPIRED")
            except (ValueError, TypeError):
                lines.append(f"Expires: {expires}")
        return "\n".join(lines)

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        """Update detail panel when selection changes."""
        idx = event.list_view.index
        if idx is not None and idx < len(self._pending):
            self._selected_idx = idx
            try:
                detail = self.query_one("#approval-detail", Static)
                detail.update(self._format_detail(self._pending[idx]))
            except Exception as e:
                log.debug("approval detail update suppressed: %s", e)

    async def action_approve_selected(self) -> None:
        """Approve the selected proposal."""
        if not self._pending:
            self.dismiss(None)
            return
        p = self._pending[self._selected_idx]
        result = await self.app.api_client.approval_approve(p["id"])
        if result:
            self.app.notify(f"Approved: {p.get('action', p['tool_name'])}")
        self.dismiss("approved")

    async def action_reject_selected(self) -> None:
        """Reject the selected proposal."""
        if not self._pending:
            self.dismiss(None)
            return
        p = self._pending[self._selected_idx]
        result = await self.app.api_client.approval_reject(p["id"])
        if result:
            self.app.notify(f"Rejected: {p.get('action', p['tool_name'])}")
        self.dismiss("rejected")
