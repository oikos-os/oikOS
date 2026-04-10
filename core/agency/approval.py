from __future__ import annotations

import hashlib
import json
import logging
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from core.interface.config import APPROVAL_PROPOSALS_LOG
from core.interface.models import ActionProposal

log = logging.getLogger(__name__)


def _make_action(tool_name: str, tool_args: dict) -> str:
    path = tool_args.get("path", "")
    content = tool_args.get("content", "")

    if "write" in tool_name and path:
        size = len(content) if isinstance(content, (str, bytes)) else 0
        return f"Write {size} bytes to {path}"
    if "edit" in tool_name and path:
        return f"Edit {path}"
    if "move" in tool_name:
        return f"Move {tool_args.get('source', '?')} \u2192 {tool_args.get('destination', '?')}"
    if "copy" in tool_name:
        return f"Copy {tool_args.get('source', '?')} \u2192 {tool_args.get('destination', '?')}"
    if "delete" in tool_name and path:
        return f"Delete {path}"
    if "navigate" in tool_name:
        return f"Navigate to {tool_args.get('url', '?')}"
    if "gmail" in tool_name or "send" in tool_name:
        return f"Send email to {tool_args.get('to', '?')}"
    if "calendar" in tool_name:
        summary = tool_args.get("summary", tool_args.get("title", "event"))
        return f"Calendar: {summary}"

    arg_keys = ", ".join(tool_args.keys()) if tool_args else "no args"
    return f"{tool_name}({arg_keys})"


class ApprovalQueue:
    def __init__(self, log_path: Path | None = None, timeout_seconds: int | None = None):
        self._log_path = log_path or APPROVAL_PROPOSALS_LOG
        if timeout_seconds is not None:
            self._timeout = timeout_seconds
        else:
            from core.interface.settings import get_setting
            self._timeout = get_setting("approval_timeout")
        self._proposals: dict[str, ActionProposal] = {}
        self._approval_cache: dict[str, float] = {}
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
                tool_args = record.get("tool_args", {})
                created[pid] = ActionProposal(
                    proposal_id=pid,
                    action_type=record["action_type"],
                    tool_name=record["tool_name"],
                    tool_args=tool_args,
                    reason=record["reason"],
                    estimated_tokens=record.get("estimated_tokens", 0),
                    risk_level=record.get("risk_level", "low"),
                    status="pending",
                    created_at=record["timestamp"],
                    room=record.get("room", ""),
                    action=_make_action(record["tool_name"], tool_args),
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
        estimated_tokens: int = 0,
        tool_args: dict | None = None,
        risk_level: str = "low",
        room: str = "",
    ) -> ActionProposal:
        now = datetime.now(timezone.utc)
        now_iso = now.isoformat()
        expires_at = (now + timedelta(seconds=self._timeout)).isoformat()
        args = tool_args or {}
        proposal = ActionProposal(
            proposal_id=uuid.uuid4().hex[:8],
            action_type=action_type,
            tool_name=tool_name,
            tool_args=args,
            reason=reason,
            estimated_tokens=estimated_tokens,
            risk_level=risk_level,
            status="pending",
            created_at=now_iso,
            room=room,
            action=_make_action(tool_name, args),
            expires_at=expires_at,
        )
        self._proposals[proposal.proposal_id] = proposal
        self._append({
            "proposal_id": proposal.proposal_id,
            "event": "created",
            "timestamp": now_iso,
            "action_type": action_type,
            "tool_name": tool_name,
            "tool_args": args,
            "reason": reason,
            "estimated_tokens": estimated_tokens,
            "risk_level": risk_level,
            "room": room,
        })
        return proposal

    def approve(self, proposal_id: str) -> ActionProposal:
        prop = self._resolve(proposal_id, "approved")
        key = self._cache_key(prop.tool_name, prop.tool_args, prop.room)
        self._approval_cache[key] = time.time() + self._timeout
        return prop

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
            if (now - created).total_seconds() >= self._timeout:
                self._resolve(prop.proposal_id, "expired")
                expired.append(prop)
        return expired

    @staticmethod
    def _cache_key(tool_name: str, tool_args: dict, room: str) -> str:
        data = json.dumps({"tool": tool_name, "args": tool_args, "room": room}, sort_keys=True)
        return hashlib.sha256(data.encode()).hexdigest()[:16]

    def is_cached(self, tool_name: str, tool_args: dict, room: str) -> bool:
        key = self._cache_key(tool_name, tool_args, room)
        ts = self._approval_cache.get(key)
        if ts is None:
            return False
        if time.time() > ts:
            del self._approval_cache[key]
            return False
        return True
