from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path

from core.interface.config import APPROVAL_PROPOSALS_LOG, APPROVAL_TIMEOUT_SECONDS
from core.interface.models import ActionProposal

log = logging.getLogger(__name__)


class ApprovalQueue:
    def __init__(self, log_path: Path | None = None, timeout_seconds: int | None = None):
        self._log_path = log_path or APPROVAL_PROPOSALS_LOG
        self._timeout = timeout_seconds if timeout_seconds is not None else APPROVAL_TIMEOUT_SECONDS
        self._proposals: dict[str, ActionProposal] = {}
        self._load()

    def _load(self) -> None:
        if not self._log_path.exists():
            return
        created: dict[str, ActionProposal] = {}
        resolved: set[str] = set()
        for line in self._log_path.read_text(encoding="utf-8").strip().split("\n"):
            if not line.strip():
                continue
            record = json.loads(line)
            pid = record["proposal_id"]
            event = record["event"]
            if event == "created":
                created[pid] = ActionProposal(
                    proposal_id=pid,
                    action_type=record["action_type"],
                    tool_name=record["tool_name"],
                    tool_args=record.get("tool_args", {}),
                    reason=record["reason"],
                    estimated_tokens=record.get("estimated_tokens", 0),
                    risk_level=record.get("risk_level", "low"),
                    status="pending",
                    created_at=record["timestamp"],
                )
            elif event in ("approved", "rejected", "expired"):
                resolved.add(pid)
                if pid in created:
                    created[pid].status = event
                    created[pid].resolved_at = record["timestamp"]
                    if event == "rejected":
                        created[pid].rejection_reason = record.get("rejection_reason")
        self._proposals = created

    def _append(self, record: dict) -> None:
        self._log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")

    def propose(
        self,
        action_type: str,
        tool_name: str,
        reason: str,
        estimated_tokens: int,
        tool_args: dict | None = None,
        risk_level: str = "low",
    ) -> ActionProposal:
        now = datetime.now(timezone.utc).isoformat()
        proposal = ActionProposal(
            proposal_id=uuid.uuid4().hex[:8],
            action_type=action_type,
            tool_name=tool_name,
            tool_args=tool_args or {},
            reason=reason,
            estimated_tokens=estimated_tokens,
            risk_level=risk_level,
            status="pending",
            created_at=now,
        )
        self._proposals[proposal.proposal_id] = proposal
        self._append({
            "proposal_id": proposal.proposal_id,
            "event": "created",
            "timestamp": now,
            "action_type": action_type,
            "tool_name": tool_name,
            "tool_args": tool_args or {},
            "reason": reason,
            "estimated_tokens": estimated_tokens,
            "risk_level": risk_level,
        })
        return proposal

    def approve(self, proposal_id: str) -> ActionProposal:
        return self._resolve(proposal_id, "approved")

    def reject(self, proposal_id: str, reason: str | None = None) -> ActionProposal:
        return self._resolve(proposal_id, "rejected", reason)

    def _resolve(self, proposal_id: str, status: str, rejection_reason: str | None = None) -> ActionProposal:
        if proposal_id not in self._proposals:
            raise KeyError(f"Unknown proposal: {proposal_id!r}")
        prop = self._proposals[proposal_id]
        if prop.status != "pending":
            raise ValueError(f"Proposal {proposal_id!r} already resolved as {prop.status!r}")
        now = datetime.now(timezone.utc).isoformat()
        prop.status = status
        prop.resolved_at = now
        if rejection_reason:
            prop.rejection_reason = rejection_reason
        record = {"proposal_id": proposal_id, "event": status, "timestamp": now}
        if rejection_reason:
            record["rejection_reason"] = rejection_reason
        self._append(record)
        return prop

    def list_pending(self) -> list[ActionProposal]:
        return [p for p in self._proposals.values() if p.status == "pending"]

    def expire_stale(self) -> list[ActionProposal]:
        now = datetime.now(timezone.utc)
        expired = []
        for prop in list(self._proposals.values()):
            if prop.status != "pending":
                continue
            created = datetime.fromisoformat(prop.created_at)
            if (now - created).total_seconds() > self._timeout:
                self._resolve(prop.proposal_id, "expired")
                expired.append(prop)
        return expired
