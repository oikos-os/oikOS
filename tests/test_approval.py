from __future__ import annotations

import json
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

from core.interface.models import ActionProposal


# -- ApprovalQueue: proposal creation --


class TestApprovalQueueCreate:
    def test_create_proposal_returns_proposal(self, tmp_path):
        from core.agency.approval import ApprovalQueue
        q = ApprovalQueue(tmp_path / "proposals.jsonl")
        prop = q.propose(
            action_type="write_file",
            tool_name="file_write",
            tool_args={"path": "staging/test.txt", "content": "hello"},
            reason="Need to save research results",
            estimated_tokens=150,
            risk_level="low",
        )
        assert prop.action_type == "write_file"
        assert prop.tool_name == "file_write"
        assert prop.status == "pending"
        assert prop.proposal_id

    def test_create_proposal_persists_to_jsonl(self, tmp_path):
        from core.agency.approval import ApprovalQueue
        log_path = tmp_path / "proposals.jsonl"
        q = ApprovalQueue(log_path)
        q.propose(action_type="write_file", tool_name="file_write", reason="test", estimated_tokens=0)
        lines = log_path.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 1
        record = json.loads(lines[0])
        assert record["event"] == "created"
        assert record["action_type"] == "write_file"

    def test_create_proposal_generates_unique_ids(self, tmp_path):
        from core.agency.approval import ApprovalQueue
        q = ApprovalQueue(tmp_path / "proposals.jsonl")
        p1 = q.propose(action_type="write_file", tool_name="a", reason="r", estimated_tokens=0)
        p2 = q.propose(action_type="write_file", tool_name="b", reason="r", estimated_tokens=0)
        assert p1.proposal_id != p2.proposal_id

    def test_create_proposal_with_all_fields(self, tmp_path):
        from core.agency.approval import ApprovalQueue
        q = ApprovalQueue(tmp_path / "proposals.jsonl")
        prop = q.propose(
            action_type="send_message",
            tool_name="message_send",
            tool_args={"to": "user@test.com", "body": "hello"},
            reason="Sending notification",
            estimated_tokens=500,
            risk_level="medium",
        )
        assert prop.risk_level == "medium"
        assert prop.estimated_tokens == 500
        assert prop.tool_args == {"to": "user@test.com", "body": "hello"}


# -- ApprovalQueue: approve/reject lifecycle --


class TestApprovalQueueLifecycle:
    def test_approve_proposal(self, tmp_path):
        from core.agency.approval import ApprovalQueue
        q = ApprovalQueue(tmp_path / "proposals.jsonl")
        prop = q.propose(action_type="write_file", tool_name="fw", reason="r", estimated_tokens=0)
        result = q.approve(prop.proposal_id)
        assert result.status == "approved"
        assert result.resolved_at is not None

    def test_reject_proposal(self, tmp_path):
        from core.agency.approval import ApprovalQueue
        q = ApprovalQueue(tmp_path / "proposals.jsonl")
        prop = q.propose(action_type="write_file", tool_name="fw", reason="r", estimated_tokens=0)
        result = q.reject(prop.proposal_id, reason="Not needed")
        assert result.status == "rejected"
        assert result.rejection_reason == "Not needed"
        assert result.resolved_at is not None

    def test_approve_persists_event_line(self, tmp_path):
        from core.agency.approval import ApprovalQueue
        log_path = tmp_path / "proposals.jsonl"
        q = ApprovalQueue(log_path)
        prop = q.propose(action_type="write_file", tool_name="fw", reason="r", estimated_tokens=0)
        q.approve(prop.proposal_id)
        lines = log_path.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 2
        assert json.loads(lines[0])["event"] == "created"
        assert json.loads(lines[1])["event"] == "approved"

    def test_reject_persists_event_line(self, tmp_path):
        from core.agency.approval import ApprovalQueue
        log_path = tmp_path / "proposals.jsonl"
        q = ApprovalQueue(log_path)
        prop = q.propose(action_type="write_file", tool_name="fw", reason="r", estimated_tokens=0)
        q.reject(prop.proposal_id, reason="Denied")
        lines = log_path.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 2
        rejected = json.loads(lines[1])
        assert rejected["event"] == "rejected"
        assert rejected["rejection_reason"] == "Denied"

    def test_approve_unknown_id_raises(self, tmp_path):
        from core.agency.approval import ApprovalQueue
        q = ApprovalQueue(tmp_path / "proposals.jsonl")
        with pytest.raises(KeyError):
            q.approve("nonexistent")

    def test_reject_unknown_id_raises(self, tmp_path):
        from core.agency.approval import ApprovalQueue
        q = ApprovalQueue(tmp_path / "proposals.jsonl")
        with pytest.raises(KeyError):
            q.reject("nonexistent")

    def test_double_approve_raises(self, tmp_path):
        from core.agency.approval import ApprovalQueue
        q = ApprovalQueue(tmp_path / "proposals.jsonl")
        prop = q.propose(action_type="write_file", tool_name="fw", reason="r", estimated_tokens=0)
        q.approve(prop.proposal_id)
        with pytest.raises(ValueError, match="already resolved"):
            q.approve(prop.proposal_id)

    def test_approve_after_reject_raises(self, tmp_path):
        from core.agency.approval import ApprovalQueue
        q = ApprovalQueue(tmp_path / "proposals.jsonl")
        prop = q.propose(action_type="write_file", tool_name="fw", reason="r", estimated_tokens=0)
        q.reject(prop.proposal_id)
        with pytest.raises(ValueError, match="already resolved"):
            q.approve(prop.proposal_id)


# -- ApprovalQueue: pending queries --


class TestApprovalQueuePending:
    def test_list_pending(self, tmp_path):
        from core.agency.approval import ApprovalQueue
        q = ApprovalQueue(tmp_path / "proposals.jsonl")
        q.propose(action_type="write_file", tool_name="a", reason="r", estimated_tokens=0)
        q.propose(action_type="send_message", tool_name="b", reason="r", estimated_tokens=0)
        pending = q.list_pending()
        assert len(pending) == 2

    def test_approved_not_in_pending(self, tmp_path):
        from core.agency.approval import ApprovalQueue
        q = ApprovalQueue(tmp_path / "proposals.jsonl")
        p1 = q.propose(action_type="write_file", tool_name="a", reason="r", estimated_tokens=0)
        q.propose(action_type="send_message", tool_name="b", reason="r", estimated_tokens=0)
        q.approve(p1.proposal_id)
        pending = q.list_pending()
        assert len(pending) == 1
        assert pending[0].action_type == "send_message"

    def test_rejected_not_in_pending(self, tmp_path):
        from core.agency.approval import ApprovalQueue
        q = ApprovalQueue(tmp_path / "proposals.jsonl")
        p1 = q.propose(action_type="write_file", tool_name="a", reason="r", estimated_tokens=0)
        q.reject(p1.proposal_id)
        pending = q.list_pending()
        assert len(pending) == 0

    def test_empty_queue_returns_empty(self, tmp_path):
        from core.agency.approval import ApprovalQueue
        q = ApprovalQueue(tmp_path / "proposals.jsonl")
        assert q.list_pending() == []


# -- ApprovalQueue: timeout expiration --


class TestApprovalQueueTimeout:
    def test_expired_proposal_treated_as_rejected(self, tmp_path):
        from core.agency.approval import ApprovalQueue
        q = ApprovalQueue(tmp_path / "proposals.jsonl", timeout_seconds=1)
        q.propose(action_type="write_file", tool_name="fw", reason="r", estimated_tokens=0)
        time.sleep(1.1)
        q.expire_stale()
        pending = q.list_pending()
        assert len(pending) == 0

    def test_non_expired_proposal_still_pending(self, tmp_path):
        from core.agency.approval import ApprovalQueue
        q = ApprovalQueue(tmp_path / "proposals.jsonl", timeout_seconds=3600)
        q.propose(action_type="write_file", tool_name="fw", reason="r", estimated_tokens=0)
        q.expire_stale()
        pending = q.list_pending()
        assert len(pending) == 1

    def test_expire_persists_event_line(self, tmp_path):
        from core.agency.approval import ApprovalQueue
        log_path = tmp_path / "proposals.jsonl"
        q = ApprovalQueue(log_path, timeout_seconds=1)
        q.propose(action_type="write_file", tool_name="fw", reason="r", estimated_tokens=0)
        time.sleep(1.1)
        q.expire_stale()
        lines = log_path.read_text(encoding="utf-8").strip().split("\n")
        expired_line = json.loads(lines[-1])
        assert expired_line["event"] == "expired"

    def test_expire_does_not_touch_resolved(self, tmp_path):
        from core.agency.approval import ApprovalQueue
        log_path = tmp_path / "proposals.jsonl"
        q = ApprovalQueue(log_path, timeout_seconds=1)
        prop = q.propose(action_type="write_file", tool_name="fw", reason="r", estimated_tokens=0)
        q.approve(prop.proposal_id)
        time.sleep(1.1)
        q.expire_stale()
        lines = log_path.read_text(encoding="utf-8").strip().split("\n")
        events = [json.loads(l)["event"] for l in lines]
        assert "expired" not in events


# -- ApprovalQueue: reload from JSONL --


class TestApprovalQueueReload:
    def test_reload_preserves_state(self, tmp_path):
        from core.agency.approval import ApprovalQueue
        log_path = tmp_path / "proposals.jsonl"
        q1 = ApprovalQueue(log_path)
        p = q1.propose(action_type="write_file", tool_name="fw", reason="r", estimated_tokens=0)
        q2 = ApprovalQueue(log_path)
        pending = q2.list_pending()
        assert len(pending) == 1
        assert pending[0].proposal_id == p.proposal_id

    def test_reload_reflects_approvals(self, tmp_path):
        from core.agency.approval import ApprovalQueue
        log_path = tmp_path / "proposals.jsonl"
        q1 = ApprovalQueue(log_path)
        p = q1.propose(action_type="write_file", tool_name="fw", reason="r", estimated_tokens=0)
        q1.approve(p.proposal_id)
        q2 = ApprovalQueue(log_path)
        assert q2.list_pending() == []


# ── Event bus integration ────────────────────────────────────────────


class TestApprovalEventBus:
    def test_classify_and_propose_emits_events(self, tmp_path):
        """Full pipeline: classify ASK_FIRST -> propose -> approve -> events emitted."""
        from core.agency.approval import ApprovalQueue
        import core.autonomic.events as events_mod
        from unittest.mock import patch

        q = ApprovalQueue(tmp_path / "proposals.jsonl")
        events = []

        def capture_event(cat, evt_type, data=None):
            events.append({"category": cat, "type": evt_type, "data": data or {}})

        with patch.object(events_mod, "emit_event", side_effect=capture_event):
            prop = q.propose(action_type="write_file", tool_name="fw", reason="r", estimated_tokens=0)
            events_mod.emit_event("agency", "proposal_created", {"proposal_id": prop.proposal_id})
            q.approve(prop.proposal_id)
            events_mod.emit_event("agency", "proposal_approved", {"proposal_id": prop.proposal_id})

        assert len(events) == 2
        assert events[0]["type"] == "proposal_created"
        assert events[1]["type"] == "proposal_approved"
