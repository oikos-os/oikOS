# Autonomy Matrix Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Define and enforce what KAIROS can do automatically (SAFE), what requires Architect approval (ASK_FIRST), and what is never automated (PROHIBITED).

**Architecture:** Rule-based action classification via JSON config (`autonomy_matrix.json`) + approval queue with append-only JSONL persistence + FastAPI endpoints + WebSocket heartbeat extension for real-time proposal delivery. Zero LLM calls. Pure CRUD + event bus integration.

**Tech Stack:** Python 3.12+, FastAPI, Pydantic, JSONL, WebSocket, pytest

**SYNTH Rulings Applied:**
- Flat action→category mapping (scope field present but ignored until Module 3)
- Extend heartbeat WebSocket (no new WS endpoint)
- Append-only JSONL (immutable audit log, no rewrite-on-status-change)
- Backend only (frontend deferred to Module 7)
- Tool registry as simple dict in autonomy.py
- Zero LLM usage

**Branch:** `feature/phase-7d-the-hands` (continue from Module 1 commits)

---

## Task 1: Config Constants + Autonomy Matrix JSON

**Files:**
- Modify: `core/interface/config.py:224-225` (add constants after AGENCY_LOG_DIR)
- Create: `autonomy_matrix.json` (project root)

**Step 1: Add config constants**

In `core/interface/config.py`, after line 224 (`AGENCY_LOG_DIR = PROJECT_ROOT / "logs" / "agency"`), add:

```python
# ── Autonomy Matrix (Phase 7d Module 2) ─────────────────────────────
AUTONOMY_MATRIX_PATH = PROJECT_ROOT / "autonomy_matrix.json"
APPROVAL_TIMEOUT_SECONDS = 3600  # 1 hour — proposals expire, treated as rejection
APPROVAL_PROPOSALS_LOG = AGENCY_LOG_DIR / "proposals.jsonl"
```

**Step 2: Create autonomy_matrix.json**

Create `autonomy_matrix.json` at the project root:

```json
{
  "version": "1.0",
  "actions": {
    "read_file": {"category": "SAFE"},
    "search_files": {"category": "SAFE"},
    "check_status": {"category": "SAFE"},
    "read_web": {"category": "SAFE"},
    "vault_search": {"category": "SAFE"},
    "write_file": {"category": "ASK_FIRST", "scope": ["staging/*"]},
    "browser_form": {"category": "ASK_FIRST"},
    "send_message": {"category": "ASK_FIRST"},
    "external_api_write": {"category": "ASK_FIRST"},
    "external_api_call": {"category": "ASK_FIRST"},
    "delete_vault": {"category": "PROHIBITED"},
    "modify_identity": {"category": "PROHIBITED"},
    "modify_source": {"category": "PROHIBITED"},
    "financial_transaction": {"category": "PROHIBITED"},
    "external_api_destructive": {"category": "PROHIBITED"}
  }
}
```

**Step 3: Commit**

```bash
git add core/interface/config.py autonomy_matrix.json
git commit -m "feat(agency): add Autonomy Matrix config constants and action definitions (Phase 7d Module 2)"
```

---

## Task 2: Pydantic Models — ActionClass + ActionProposal

**Files:**
- Modify: `core/interface/models.py:235` (add after GauntletVerdict enum)
- Test: `tests/test_autonomy.py` (will be created in Task 3)

**Step 1: Add models to `core/interface/models.py`**

After the `GauntletVerdict` enum (line 235), add:

```python
# ── Phase 7d: Autonomy Matrix models ────────────────────────────────


class ActionClass(str, Enum):
    SAFE = "SAFE"
    ASK_FIRST = "ASK_FIRST"
    PROHIBITED = "PROHIBITED"


class ActionProposal(BaseModel):
    """A proposal for an ASK_FIRST action awaiting Architect approval."""

    proposal_id: str
    action_type: str  # key from autonomy_matrix.json (e.g., "write_file")
    tool_name: str  # concrete tool that triggered this (e.g., "file_write")
    tool_args: dict = Field(default_factory=dict)
    reason: str  # why KAIROS wants to do this
    estimated_tokens: int = 0  # from TokenBudget
    risk_level: str = "low"  # "low", "medium", "high"
    status: str = "pending"  # "pending", "approved", "rejected", "expired"
    created_at: str  # ISO 8601
    resolved_at: str | None = None  # ISO 8601, set on approve/reject/expire
    rejection_reason: str | None = None  # set on rejection
```

**Step 2: Commit**

```bash
git add core/interface/models.py
git commit -m "feat(agency): add ActionClass enum and ActionProposal model (Phase 7d Module 2)"
```

---

## Task 3: Action Classification — AutonomyMatrix + Tool Registry

**Files:**
- Create: `core/agency/autonomy.py`
- Create: `tests/test_autonomy.py`

**Step 1: Write the failing tests**

Create `tests/test_autonomy.py`:

```python
from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from core.interface.models import ActionClass


# ── AutonomyMatrix: classification ───────────────────────────────────


class TestAutonomyMatrixClassification:
    def test_safe_action_classified(self, tmp_path):
        from core.agency.autonomy import AutonomyMatrix

        matrix = _make_matrix(tmp_path, {"read_file": {"category": "SAFE"}})
        assert matrix.classify("read_file") == ActionClass.SAFE

    def test_ask_first_action_classified(self, tmp_path):
        from core.agency.autonomy import AutonomyMatrix

        matrix = _make_matrix(tmp_path, {"write_file": {"category": "ASK_FIRST"}})
        assert matrix.classify("write_file") == ActionClass.ASK_FIRST

    def test_prohibited_action_classified(self, tmp_path):
        from core.agency.autonomy import AutonomyMatrix

        matrix = _make_matrix(tmp_path, {"delete_vault": {"category": "PROHIBITED"}})
        assert matrix.classify("delete_vault") == ActionClass.PROHIBITED

    def test_unknown_action_defaults_to_prohibited(self, tmp_path):
        from core.agency.autonomy import AutonomyMatrix

        matrix = _make_matrix(tmp_path, {"read_file": {"category": "SAFE"}})
        assert matrix.classify("unknown_action") == ActionClass.PROHIBITED

    def test_all_safe_actions_from_default_config(self, tmp_path):
        from core.agency.autonomy import AutonomyMatrix

        matrix = _make_matrix(tmp_path, {
            "read_file": {"category": "SAFE"},
            "search_files": {"category": "SAFE"},
            "check_status": {"category": "SAFE"},
            "read_web": {"category": "SAFE"},
            "vault_search": {"category": "SAFE"},
        })
        for action in ["read_file", "search_files", "check_status", "read_web", "vault_search"]:
            assert matrix.classify(action) == ActionClass.SAFE

    def test_all_prohibited_actions_from_default_config(self, tmp_path):
        from core.agency.autonomy import AutonomyMatrix

        matrix = _make_matrix(tmp_path, {
            "delete_vault": {"category": "PROHIBITED"},
            "modify_identity": {"category": "PROHIBITED"},
            "modify_source": {"category": "PROHIBITED"},
            "financial_transaction": {"category": "PROHIBITED"},
            "external_api_destructive": {"category": "PROHIBITED"},
        })
        for action in ["delete_vault", "modify_identity", "modify_source",
                        "financial_transaction", "external_api_destructive"]:
            assert matrix.classify(action) == ActionClass.PROHIBITED

    def test_scope_field_present_but_ignored(self, tmp_path):
        """Module 2 reads category only. Scope is for Module 3."""
        from core.agency.autonomy import AutonomyMatrix

        matrix = _make_matrix(tmp_path, {
            "write_file": {"category": "ASK_FIRST", "scope": ["staging/*"]},
        })
        assert matrix.classify("write_file") == ActionClass.ASK_FIRST

    def test_invalid_category_raises(self, tmp_path):
        from core.agency.autonomy import AutonomyMatrix

        with pytest.raises(ValueError, match="Invalid category"):
            _make_matrix(tmp_path, {"bad": {"category": "YOLO"}})


# ── AutonomyMatrix: config loading ───────────────────────────────────


class TestAutonomyMatrixConfig:
    def test_loads_from_json_file(self, tmp_path):
        from core.agency.autonomy import AutonomyMatrix

        matrix = _make_matrix(tmp_path, {"read_file": {"category": "SAFE"}})
        assert matrix.classify("read_file") == ActionClass.SAFE

    def test_raises_on_missing_config(self, tmp_path):
        from core.agency.autonomy import AutonomyMatrix

        with pytest.raises(FileNotFoundError):
            AutonomyMatrix(tmp_path / "nonexistent.json")

    def test_raises_on_invalid_json(self, tmp_path):
        from core.agency.autonomy import AutonomyMatrix

        bad_file = tmp_path / "bad.json"
        bad_file.write_text("not json", encoding="utf-8")
        with pytest.raises((json.JSONDecodeError, KeyError)):
            AutonomyMatrix(bad_file)

    def test_version_field_accepted(self, tmp_path):
        from core.agency.autonomy import AutonomyMatrix

        config = {"version": "1.0", "actions": {"read_file": {"category": "SAFE"}}}
        f = tmp_path / "matrix.json"
        f.write_text(json.dumps(config), encoding="utf-8")
        matrix = AutonomyMatrix(f)
        assert matrix.classify("read_file") == ActionClass.SAFE


# ── Tool Registry ────────────────────────────────────────────────────


class TestToolRegistry:
    def test_known_tool_resolves_to_action_type(self, tmp_path):
        from core.agency.autonomy import AutonomyMatrix

        matrix = _make_matrix(tmp_path, {
            "read_file": {"category": "SAFE"},
            "write_file": {"category": "ASK_FIRST"},
        })
        assert matrix.classify_tool("file_read") == ActionClass.SAFE
        assert matrix.classify_tool("file_write") == ActionClass.ASK_FIRST

    def test_unknown_tool_defaults_to_prohibited(self, tmp_path):
        from core.agency.autonomy import AutonomyMatrix

        matrix = _make_matrix(tmp_path, {"read_file": {"category": "SAFE"}})
        assert matrix.classify_tool("unknown_tool") == ActionClass.PROHIBITED

    def test_custom_tool_registry(self, tmp_path):
        from core.agency.autonomy import AutonomyMatrix

        matrix = _make_matrix(tmp_path, {"write_file": {"category": "ASK_FIRST"}})
        matrix.register_tool("my_custom_writer", "write_file")
        assert matrix.classify_tool("my_custom_writer") == ActionClass.ASK_FIRST


# ── Security: prompt injection bypass ────────────────────────────────


class TestAutonomyMatrixSecurity:
    def test_prompt_injection_cannot_reclassify(self, tmp_path):
        """Classification is config-driven, not prompt-derived."""
        from core.agency.autonomy import AutonomyMatrix

        matrix = _make_matrix(tmp_path, {"delete_vault": {"category": "PROHIBITED"}})
        # Simulate a crafted action name that tries to inject
        assert matrix.classify("delete_vault; category=SAFE") == ActionClass.PROHIBITED
        assert matrix.classify("SAFE") == ActionClass.PROHIBITED

    def test_classify_is_case_sensitive(self, tmp_path):
        from core.agency.autonomy import AutonomyMatrix

        matrix = _make_matrix(tmp_path, {"read_file": {"category": "SAFE"}})
        assert matrix.classify("READ_FILE") == ActionClass.PROHIBITED  # unknown
        assert matrix.classify("read_file") == ActionClass.SAFE


# ── Helper ───────────────────────────────────────────────────────────


def _make_matrix(tmp_path, actions):
    from core.agency.autonomy import AutonomyMatrix

    config = {"version": "1.0", "actions": actions}
    f = tmp_path / "matrix.json"
    f.write_text(json.dumps(config), encoding="utf-8")
    return AutonomyMatrix(f)
```

**Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_autonomy.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.agency.autonomy'`

**Step 3: Write implementation**

Create `core/agency/autonomy.py`:

```python
from __future__ import annotations

import json
import logging
from pathlib import Path

from core.interface.models import ActionClass

log = logging.getLogger(__name__)

# ── Tool Registry ────────────────────────────────────────────────────
# Maps concrete tool names to abstract action types in the matrix.
# Module 2 ships the base mapping; Module 3+ extends it.
_DEFAULT_TOOL_REGISTRY: dict[str, str] = {
    "file_read": "read_file",
    "file_search": "search_files",
    "system_status": "check_status",
    "web_navigate": "read_web",
    "vault_search": "vault_search",
    "file_write": "write_file",
    "browser_submit": "browser_form",
    "message_send": "send_message",
    "api_write": "external_api_write",
    "api_call": "external_api_call",
    "vault_delete": "delete_vault",
    "identity_modify": "modify_identity",
    "source_modify": "modify_source",
}


class AutonomyMatrix:
    def __init__(self, config_path: Path):
        if not config_path.exists():
            raise FileNotFoundError(f"Autonomy matrix config not found: {config_path}")
        raw = json.loads(config_path.read_text(encoding="utf-8"))
        actions = raw["actions"]
        self._rules: dict[str, ActionClass] = {}
        valid = {e.value for e in ActionClass}
        for action_type, entry in actions.items():
            cat = entry["category"]
            if cat not in valid:
                raise ValueError(f"Invalid category {cat!r} for action {action_type!r}")
            self._rules[action_type] = ActionClass(cat)
        self._tool_registry: dict[str, str] = dict(_DEFAULT_TOOL_REGISTRY)

    def classify(self, action_type: str) -> ActionClass:
        return self._rules.get(action_type, ActionClass.PROHIBITED)

    def classify_tool(self, tool_name: str) -> ActionClass:
        action_type = self._tool_registry.get(tool_name)
        if action_type is None:
            return ActionClass.PROHIBITED
        return self.classify(action_type)

    def register_tool(self, tool_name: str, action_type: str) -> None:
        self._tool_registry[tool_name] = action_type
```

**Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_autonomy.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add core/agency/autonomy.py tests/test_autonomy.py
git commit -m "feat(agency): add AutonomyMatrix action classification (Phase 7d Module 2.1)"
```

---

## Task 4: Approval Queue — Core Logic

**Files:**
- Create: `core/agency/approval.py`
- Create: `tests/test_approval.py`

**Step 1: Write the failing tests**

Create `tests/test_approval.py`:

```python
from __future__ import annotations

import json
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

from core.interface.models import ActionProposal


# ── ApprovalQueue: proposal creation ─────────────────────────────────


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
        q.propose(
            action_type="write_file", tool_name="file_write",
            reason="test", estimated_tokens=0,
        )
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


# ── ApprovalQueue: approve/reject lifecycle ──────────────────────────


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


# ── ApprovalQueue: pending queries ───────────────────────────────────


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


# ── ApprovalQueue: timeout expiration ────────────────────────────────


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
        # Should only have 2 lines: created + approved (no expired line for already-resolved)
        lines = log_path.read_text(encoding="utf-8").strip().split("\n")
        events = [json.loads(l)["event"] for l in lines]
        assert "expired" not in events


# ── ApprovalQueue: reload from JSONL ─────────────────────────────────


class TestApprovalQueueReload:
    def test_reload_preserves_state(self, tmp_path):
        from core.agency.approval import ApprovalQueue

        log_path = tmp_path / "proposals.jsonl"
        q1 = ApprovalQueue(log_path)
        p = q1.propose(action_type="write_file", tool_name="fw", reason="r", estimated_tokens=0)

        # Create a new queue instance from same file — simulates server restart
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
```

**Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_approval.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.agency.approval'`

**Step 3: Write implementation**

Create `core/agency/approval.py`:

```python
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone, timedelta
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
```

**Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_approval.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add core/agency/approval.py tests/test_approval.py
git commit -m "feat(agency): add ApprovalQueue with append-only JSONL persistence (Phase 7d Module 2.2)"
```

---

## Task 5: FastAPI Routes + Event Bus Integration

**Files:**
- Create: `core/interface/api/routes/agency.py`
- Modify: `core/interface/api/server.py:88` (add route registration)
- Create: `tests/test_agency_routes.py`

**Step 1: Write the failing tests**

Create `tests/test_agency_routes.py`:

```python
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def app(tmp_path):
    """Create test app with agency routes."""
    from fastapi import FastAPI
    from core.interface.api.routes.agency import router, _get_queue

    app = FastAPI()
    log_path = tmp_path / "proposals.jsonl"

    # Override the queue dependency
    from core.agency.approval import ApprovalQueue
    queue = ApprovalQueue(log_path)

    def override_queue():
        return queue

    app.dependency_overrides[_get_queue] = override_queue
    app.include_router(router, prefix="/api/agency")
    return app, queue


@pytest.fixture
def client(app):
    app_instance, _ = app
    return TestClient(app_instance)


# ── POST /api/agency/propose ─────────────────────────────────────────


class TestProposeEndpoint:
    def test_propose_returns_201(self, app):
        app_instance, _ = app
        client = TestClient(app_instance)
        resp = client.post("/api/agency/propose", json={
            "action_type": "write_file",
            "tool_name": "file_write",
            "reason": "Save results",
            "estimated_tokens": 100,
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["status"] == "pending"
        assert data["proposal_id"]

    def test_propose_emits_event(self, app):
        app_instance, _ = app
        client = TestClient(app_instance)
        with patch("core.interface.api.routes.agency.emit_event") as mock_emit:
            client.post("/api/agency/propose", json={
                "action_type": "write_file",
                "tool_name": "file_write",
                "reason": "test",
                "estimated_tokens": 0,
            })
            mock_emit.assert_called_once()
            call_args = mock_emit.call_args
            assert call_args[0][0] == "agency"
            assert call_args[0][1] == "proposal_created"


# ── POST /api/agency/approve/{id} ───────────────────────────────────


class TestApproveEndpoint:
    def test_approve_returns_200(self, app):
        app_instance, queue = app
        client = TestClient(app_instance)
        prop = queue.propose(action_type="write_file", tool_name="fw", reason="r", estimated_tokens=0)
        resp = client.post(f"/api/agency/approve/{prop.proposal_id}")
        assert resp.status_code == 200
        assert resp.json()["status"] == "approved"

    def test_approve_unknown_returns_404(self, app):
        app_instance, _ = app
        client = TestClient(app_instance)
        resp = client.post("/api/agency/approve/nonexistent")
        assert resp.status_code == 404

    def test_approve_emits_event(self, app):
        app_instance, queue = app
        client = TestClient(app_instance)
        prop = queue.propose(action_type="write_file", tool_name="fw", reason="r", estimated_tokens=0)
        with patch("core.interface.api.routes.agency.emit_event") as mock_emit:
            client.post(f"/api/agency/approve/{prop.proposal_id}")
            mock_emit.assert_called_once()
            assert mock_emit.call_args[0][1] == "proposal_approved"


# ── POST /api/agency/reject/{id} ────────────────────────────────────


class TestRejectEndpoint:
    def test_reject_returns_200(self, app):
        app_instance, queue = app
        client = TestClient(app_instance)
        prop = queue.propose(action_type="write_file", tool_name="fw", reason="r", estimated_tokens=0)
        resp = client.post(f"/api/agency/reject/{prop.proposal_id}", json={"reason": "Denied"})
        assert resp.status_code == 200
        assert resp.json()["status"] == "rejected"

    def test_reject_without_reason(self, app):
        app_instance, queue = app
        client = TestClient(app_instance)
        prop = queue.propose(action_type="write_file", tool_name="fw", reason="r", estimated_tokens=0)
        resp = client.post(f"/api/agency/reject/{prop.proposal_id}")
        assert resp.status_code == 200

    def test_reject_emits_event(self, app):
        app_instance, queue = app
        client = TestClient(app_instance)
        prop = queue.propose(action_type="write_file", tool_name="fw", reason="r", estimated_tokens=0)
        with patch("core.interface.api.routes.agency.emit_event") as mock_emit:
            client.post(f"/api/agency/reject/{prop.proposal_id}")
            mock_emit.assert_called_once()
            assert mock_emit.call_args[0][1] == "proposal_rejected"


# ── GET /api/agency/pending ──────────────────────────────────────────


class TestPendingEndpoint:
    def test_pending_returns_list(self, app):
        app_instance, queue = app
        client = TestClient(app_instance)
        queue.propose(action_type="write_file", tool_name="a", reason="r", estimated_tokens=0)
        queue.propose(action_type="send_message", tool_name="b", reason="r", estimated_tokens=0)
        resp = client.get("/api/agency/pending")
        assert resp.status_code == 200
        assert len(resp.json()) == 2

    def test_pending_empty(self, app):
        app_instance, _ = app
        client = TestClient(app_instance)
        resp = client.get("/api/agency/pending")
        assert resp.status_code == 200
        assert resp.json() == []
```

**Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_agency_routes.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.interface.api.routes.agency'`

**Step 3: Write implementation**

Create `core/interface/api/routes/agency.py`:

```python
"""Agency endpoints — autonomy matrix proposals, approval queue."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from core.autonomic.events import emit_event

router = APIRouter()


# ── Dependency ───────────────────────────────────────────────────────

def _get_queue():
    from core.agency.approval import ApprovalQueue
    return ApprovalQueue()


# ── Request models ───────────────────────────────────────────────────

class ProposeRequest(BaseModel):
    action_type: str
    tool_name: str
    tool_args: dict = {}
    reason: str
    estimated_tokens: int = 0
    risk_level: str = "low"


class RejectRequest(BaseModel):
    reason: str | None = None


# ── Endpoints ────────────────────────────────────────────────────────

@router.post("/propose", status_code=201)
def propose_action(req: ProposeRequest, queue=Depends(_get_queue)):
    prop = queue.propose(
        action_type=req.action_type,
        tool_name=req.tool_name,
        tool_args=req.tool_args,
        reason=req.reason,
        estimated_tokens=req.estimated_tokens,
        risk_level=req.risk_level,
    )
    emit_event("agency", "proposal_created", {
        "proposal_id": prop.proposal_id,
        "action_type": req.action_type,
        "tool_name": req.tool_name,
    })
    return prop.model_dump()


@router.post("/approve/{proposal_id}")
def approve_action(proposal_id: str, queue=Depends(_get_queue)):
    try:
        prop = queue.approve(proposal_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Proposal {proposal_id!r} not found")
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    emit_event("agency", "proposal_approved", {"proposal_id": proposal_id})
    return prop.model_dump()


@router.post("/reject/{proposal_id}")
def reject_action(proposal_id: str, req: RejectRequest | None = None, queue=Depends(_get_queue)):
    reason = req.reason if req else None
    try:
        prop = queue.reject(proposal_id, reason=reason)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Proposal {proposal_id!r} not found")
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    emit_event("agency", "proposal_rejected", {
        "proposal_id": proposal_id,
        "rejection_reason": reason,
    })
    return prop.model_dump()


@router.get("/pending")
def list_pending(queue=Depends(_get_queue)):
    return [p.model_dump() for p in queue.list_pending()]
```

**Step 4: Register the route in server.py**

In `core/interface/api/server.py`, after line 87 (`from core.interface.api.routes.search import router as search_router`), add:

```python
    from core.interface.api.routes.agency import router as agency_router
```

After line 114 (`app.include_router(search_router, prefix="/api", dependencies=auth_dep)`), add:

```python
    app.include_router(agency_router, prefix="/api/agency", dependencies=auth_dep)
```

**Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_agency_routes.py -v`
Expected: All PASS

**Step 6: Commit**

```bash
git add core/interface/api/routes/agency.py core/interface/api/server.py tests/test_agency_routes.py
git commit -m "feat(agency): add FastAPI approval endpoints with event bus integration (Phase 7d Module 2)"
```

---

## Task 6: WebSocket Heartbeat Extension

**Files:**
- Modify: `core/interface/api/ws/heartbeat.py:26-29` (add pending_proposals to payload)
- Create: `tests/test_heartbeat_proposals.py`

**Step 1: Write the failing test**

Create `tests/test_heartbeat_proposals.py`:

```python
from __future__ import annotations

import json
from unittest.mock import patch, MagicMock

import pytest


class TestHeartbeatProposals:
    def test_heartbeat_payload_includes_pending_proposals(self):
        """Verify the heartbeat payload builder includes pending proposals."""
        from core.interface.api.ws.heartbeat import _build_heartbeat_payload

        mock_status = {"running": True, "pid": 1234}
        mock_state = MagicMock()
        mock_state.value = "idle"

        with patch("core.interface.api.ws.heartbeat.get_status", return_value=mock_status), \
             patch("core.interface.api.ws.heartbeat.get_current_state", return_value=mock_state), \
             patch("core.interface.api.ws.heartbeat._get_pending_proposals", return_value=[]):
            payload = _build_heartbeat_payload()
            assert "pending_proposals" in payload
            assert payload["pending_proposals"] == []

    def test_heartbeat_includes_proposal_data(self):
        from core.interface.api.ws.heartbeat import _build_heartbeat_payload

        mock_proposal = {
            "proposal_id": "abc123",
            "action_type": "write_file",
            "status": "pending",
        }

        mock_status = {"running": True}
        mock_state = MagicMock()
        mock_state.value = "idle"

        with patch("core.interface.api.ws.heartbeat.get_status", return_value=mock_status), \
             patch("core.interface.api.ws.heartbeat.get_current_state", return_value=mock_state), \
             patch("core.interface.api.ws.heartbeat._get_pending_proposals", return_value=[mock_proposal]):
            payload = _build_heartbeat_payload()
            assert len(payload["pending_proposals"]) == 1
            assert payload["pending_proposals"][0]["proposal_id"] == "abc123"

    def test_pending_proposals_helper_handles_missing_log(self):
        from core.interface.api.ws.heartbeat import _get_pending_proposals

        with patch("core.interface.api.ws.heartbeat.APPROVAL_PROPOSALS_LOG") as mock_path:
            mock_path.exists.return_value = False
            assert _get_pending_proposals() == []
```

**Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_heartbeat_proposals.py -v`
Expected: FAIL — `ImportError: cannot import name '_build_heartbeat_payload'`

**Step 3: Modify heartbeat.py**

Replace the heartbeat.py content to extract the payload building into a testable function and add pending proposals:

In `core/interface/api/ws/heartbeat.py`, the current payload block (lines 23-29) is:

```python
            from core.autonomic.daemon import get_status
            from core.autonomic.fsm import get_current_state

            payload = {
                "fsm_state": get_current_state().value,
                "daemon": get_status(),
            }
```

Replace the full file with:

```python
"""WebSocket heartbeat — pushes daemon + FSM state + pending proposals every 30s."""

from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from core.interface.api.auth import validate_ws_token
from core.interface.config import APPROVAL_PROPOSALS_LOG

log = logging.getLogger(__name__)

router = APIRouter()


def _get_pending_proposals() -> list[dict]:
    """Read pending proposals for heartbeat payload. Best-effort, never raises."""
    try:
        if not APPROVAL_PROPOSALS_LOG.exists():
            return []
        from core.agency.approval import ApprovalQueue
        queue = ApprovalQueue(APPROVAL_PROPOSALS_LOG)
        return [p.model_dump() for p in queue.list_pending()]
    except Exception:
        return []


def _build_heartbeat_payload() -> dict:
    from core.autonomic.daemon import get_status
    from core.autonomic.fsm import get_current_state

    return {
        "fsm_state": get_current_state().value,
        "daemon": get_status(),
        "pending_proposals": _get_pending_proposals(),
    }


@router.websocket("/ws/heartbeat")
async def heartbeat(ws: WebSocket, token: str | None = Query(None)):
    if not validate_ws_token(token):
        await ws.close(code=4001, reason="Unauthorized")
        return
    await ws.accept()
    try:
        while True:
            payload = _build_heartbeat_payload()
            await ws.send_text(json.dumps(payload))
            await asyncio.sleep(30)
    except WebSocketDisconnect:
        asyncio.get_event_loop().call_later(60, _try_close_session)
    except Exception:
        pass


def _try_close_session():
    """Attempt session close after WS disconnect grace period."""
    try:
        from core.memory.session import close_session
        close_session(reason="ws_disconnect")
    except Exception:
        pass
```

**Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_heartbeat_proposals.py -v`
Expected: All PASS

**Step 5: Run all existing tests to verify no regression**

Run: `python -m pytest tests/ -x -q`
Expected: All pass (677+ Python tests)

**Step 6: Commit**

```bash
git add core/interface/api/ws/heartbeat.py tests/test_heartbeat_proposals.py
git commit -m "feat(agency): extend WebSocket heartbeat with pending proposals (Phase 7d Module 2)"
```

---

## Task 7: Integration Tests — End-to-End Classification + Approval

**Files:**
- Modify: `tests/test_autonomy.py` (add integration tests at the bottom)
- Modify: `tests/test_approval.py` (add event bus integration test at the bottom)

**Step 1: Add integration tests to test_autonomy.py**

Append to `tests/test_autonomy.py`:

```python
# ── Integration: SAFE action auto-executes and logs ──────────────────


class TestAutonomyIntegration:
    def test_safe_action_auto_executes(self, tmp_path):
        """SAFE action: classify → permitted → no proposal needed."""
        from core.agency.autonomy import AutonomyMatrix

        matrix = _make_matrix(tmp_path, {
            "read_file": {"category": "SAFE"},
            "delete_vault": {"category": "PROHIBITED"},
        })
        classification = matrix.classify("read_file")
        assert classification == ActionClass.SAFE
        # SAFE actions proceed without approval queue involvement

    def test_prohibited_action_blocked_with_message(self, tmp_path):
        """PROHIBITED action: classify → blocked → clear error context."""
        from core.agency.autonomy import AutonomyMatrix

        matrix = _make_matrix(tmp_path, {"delete_vault": {"category": "PROHIBITED"}})
        classification = matrix.classify("delete_vault")
        assert classification == ActionClass.PROHIBITED
        # Caller checks classification and blocks execution

    def test_ask_first_action_requires_proposal(self, tmp_path):
        """ASK_FIRST action: classify → must create proposal → wait for approval."""
        from core.agency.autonomy import AutonomyMatrix
        from core.agency.approval import ApprovalQueue

        matrix = _make_matrix(tmp_path, {"write_file": {"category": "ASK_FIRST"}})
        classification = matrix.classify("write_file")
        assert classification == ActionClass.ASK_FIRST

        # ASK_FIRST triggers proposal creation
        q = ApprovalQueue(tmp_path / "proposals.jsonl")
        prop = q.propose(
            action_type="write_file",
            tool_name="file_write",
            reason="Save research",
            estimated_tokens=200,
        )
        assert prop.status == "pending"

        # Architect approves
        result = q.approve(prop.proposal_id)
        assert result.status == "approved"

    def test_full_tool_classification_pipeline(self, tmp_path):
        """Tool name → action type → classification → decision."""
        from core.agency.autonomy import AutonomyMatrix

        matrix = _make_matrix(tmp_path, {
            "read_file": {"category": "SAFE"},
            "write_file": {"category": "ASK_FIRST"},
            "delete_vault": {"category": "PROHIBITED"},
        })
        # Tool → action_type → classification
        assert matrix.classify_tool("file_read") == ActionClass.SAFE
        assert matrix.classify_tool("file_write") == ActionClass.ASK_FIRST
        assert matrix.classify_tool("vault_delete") == ActionClass.PROHIBITED
        assert matrix.classify_tool("unknown") == ActionClass.PROHIBITED

    def test_loads_real_autonomy_matrix_json(self):
        """Verify the shipped autonomy_matrix.json is valid and loadable."""
        from core.agency.autonomy import AutonomyMatrix
        from core.interface.config import AUTONOMY_MATRIX_PATH

        if not AUTONOMY_MATRIX_PATH.exists():
            pytest.skip("autonomy_matrix.json not found")
        matrix = AutonomyMatrix(AUTONOMY_MATRIX_PATH)
        # Verify a few known classifications from the shipped config
        assert matrix.classify("read_file") == ActionClass.SAFE
        assert matrix.classify("write_file") == ActionClass.ASK_FIRST
        assert matrix.classify("delete_vault") == ActionClass.PROHIBITED
```

**Step 2: Add event bus integration test to test_approval.py**

Append to `tests/test_approval.py`:

```python
# ── Event bus integration ────────────────────────────────────────────


class TestApprovalEventBus:
    def test_classify_and_propose_emits_events(self, tmp_path):
        """Full pipeline: classify ASK_FIRST → propose → approve → events emitted."""
        from core.agency.approval import ApprovalQueue
        from core.autonomic.events import emit_event
        from unittest.mock import patch

        q = ApprovalQueue(tmp_path / "proposals.jsonl")
        events = []

        def capture_event(cat, evt_type, data=None):
            events.append({"category": cat, "type": evt_type, "data": data or {}})

        with patch("core.autonomic.events.emit_event", side_effect=capture_event):
            # These would be called by the route handler, simulated here
            prop = q.propose(action_type="write_file", tool_name="fw", reason="r", estimated_tokens=0)
            emit_event("agency", "proposal_created", {"proposal_id": prop.proposal_id})
            q.approve(prop.proposal_id)
            emit_event("agency", "proposal_approved", {"proposal_id": prop.proposal_id})

        assert len(events) == 2
        assert events[0]["type"] == "proposal_created"
        assert events[1]["type"] == "proposal_approved"
```

**Step 3: Run all Module 2 tests**

Run: `python -m pytest tests/test_autonomy.py tests/test_approval.py tests/test_agency_routes.py tests/test_heartbeat_proposals.py -v`
Expected: All PASS

**Step 4: Run full test suite**

Run: `python -m pytest tests/ -x -q`
Expected: All pass (no regressions)

**Step 5: Commit**

```bash
git add tests/test_autonomy.py tests/test_approval.py
git commit -m "test(agency): add integration tests for autonomy classification + approval pipeline (Phase 7d Module 2)"
```

---

## Summary

| Task | Component | New Files | Modified Files | Est. Tests |
|------|-----------|-----------|----------------|------------|
| 1 | Config + JSON | `autonomy_matrix.json` | `config.py` | 0 |
| 2 | Pydantic models | — | `models.py` | 0 |
| 3 | Action Classification | `autonomy.py`, `test_autonomy.py` | — | 17 |
| 4 | Approval Queue | `approval.py`, `test_approval.py` | — | 20 |
| 5 | FastAPI Routes | `agency.py`, `test_agency_routes.py` | `server.py` | 10 |
| 6 | WebSocket Extension | `test_heartbeat_proposals.py` | `heartbeat.py` | 3 |
| 7 | Integration Tests | — | `test_autonomy.py`, `test_approval.py` | 7 |
| **Total** | | **5 new files** | **4 modified files** | **~57** |

**Commits:** 7 (one per task, one logical unit each)
**LLM calls:** 0 (pure rule-based, per SYNTH ruling)
**New dependencies:** 0 (via negativa)
