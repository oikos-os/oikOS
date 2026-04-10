# T-102: Approval UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the user-facing approval interface so ASK_FIRST tools can be reviewed, approved, or rejected by the user via TUI, CLI, and API.

**Architecture:** Option A (polling). Middleware returns "awaiting approval" immediately. TUI polls for pending approvals on a 3-second interval. Approved tool+args+room hashes are cached so retry calls auto-approve. No blocking coroutines.

**Tech Stack:** FastAPI (API), Textual (TUI), Click (CLI), httpx (TUI client), pytest (tests)

---

## File Map

### Modified Files

| File | Changes |
|---|---|
| `core/interface/models.py:284` | Add `room`, `expires_at`, `action` fields to ActionProposal |
| `core/interface/config.py` | APPROVAL_TIMEOUT_SECONDS: 3600 → 300 |
| `core/agency/approval.py` | Room param, expires_at calc, action generation, approval cache |
| `core/framework/middleware/autonomy.py` | Check approval cache before proposing, pass room |
| `core/interface/api/routes/agency.py` | New endpoints, enhanced response shape |
| `core/interface/api/server.py` | Change prefix from `/api/agency` to `/api/approvals` |
| `core/interface/tui/app.py` | Add F9 binding, ApprovalBar widget, polling timer |
| `core/interface/tui/client.py` | Add approval API methods |
| `core/interface/tui/styles.tcss` | Approval bar + modal styles |
| `core/interface/cli.py` | Add `approvals` command group |
| `core/framework/middleware/error_handler.py` | Include `room` and `action` in approval_required response |

### New Files

| File | Purpose |
|---|---|
| `core/interface/tui/widgets/approval_bar.py` | Persistent amber notification bar above footer |
| `core/interface/tui/views/approvals.py` | F9 modal screen for reviewing/acting on approvals |
| `tests/test_approval_ui.py` | Tests for all T-102 changes |

---

## Task 1: ActionProposal Model + Config

**Files:**
- Modify: `core/interface/models.py:284-297`
- Modify: `core/interface/config.py`
- Test: `tests/test_approval_ui.py`

- [ ] **Step 1: Write failing test for new ActionProposal fields**

```python
# tests/test_approval_ui.py
"""Tests for T-102: Approval UI."""
from __future__ import annotations

import pytest


class TestActionProposalModel:
    def test_new_fields_have_defaults(self):
        from core.interface.models import ActionProposal

        prop = ActionProposal(
            proposal_id="abc12345",
            action_type="write_file",
            tool_name="oikos_fs_write",
            reason="test",
            created_at="2026-03-31T00:00:00+00:00",
        )
        assert prop.room == ""
        assert prop.expires_at is None
        assert prop.action == ""

    def test_fields_accept_values(self):
        from core.interface.models import ActionProposal

        prop = ActionProposal(
            proposal_id="abc12345",
            action_type="write_file",
            tool_name="oikos_fs_write",
            reason="test",
            created_at="2026-03-31T00:00:00+00:00",
            room="home",
            expires_at="2026-03-31T00:05:00+00:00",
            action="Write 340 bytes to notes.md",
        )
        assert prop.room == "home"
        assert prop.expires_at == "2026-03-31T00:05:00+00:00"
        assert prop.action == "Write 340 bytes to notes.md"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_approval_ui.py::TestActionProposalModel -v`
Expected: FAIL — `room`, `expires_at`, `action` fields not defined on ActionProposal.

- [ ] **Step 3: Add new fields to ActionProposal**

In `core/interface/models.py`, add three fields to ActionProposal (after `risk_level`):

```python
    room: str = ""  # which room triggered this
    action: str = ""  # human-readable action description
    expires_at: str | None = None  # ISO 8601, auto-reject deadline
```

- [ ] **Step 4: Update config timeout**

In `core/interface/config.py`, change:

```python
APPROVAL_TIMEOUT_SECONDS = 300  # 5 minutes (T-102)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest tests/test_approval_ui.py::TestActionProposalModel -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add core/interface/models.py core/interface/config.py tests/test_approval_ui.py
git commit -m "feat: add room, action, expires_at fields to ActionProposal (T-102)"
```

---

## Task 2: ApprovalQueue Enhancement

**Files:**
- Modify: `core/agency/approval.py`
- Test: `tests/test_approval_ui.py`

- [ ] **Step 1: Write failing tests for queue enhancements**

Append to `tests/test_approval_ui.py`:

```python
import time
from unittest.mock import patch


class TestApprovalQueueEnhancements:
    def _make_queue(self, timeout=300, tmp_path=None):
        from core.agency.approval import ApprovalQueue

        log_path = tmp_path / "proposals.jsonl" if tmp_path else None
        return ApprovalQueue(log_path=log_path, timeout_seconds=timeout)

    def test_propose_sets_room(self, tmp_path):
        q = self._make_queue(tmp_path=tmp_path)
        prop = q.propose(
            action_type="write_file",
            tool_name="oikos_fs_write",
            reason="test",
            estimated_tokens=0,
            room="home",
        )
        assert prop.room == "home"

    def test_propose_sets_expires_at(self, tmp_path):
        q = self._make_queue(timeout=300, tmp_path=tmp_path)
        prop = q.propose(
            action_type="write_file",
            tool_name="oikos_fs_write",
            reason="test",
            estimated_tokens=0,
        )
        assert prop.expires_at is not None
        # expires_at should be ~5 minutes after created_at
        from datetime import datetime

        created = datetime.fromisoformat(prop.created_at)
        expires = datetime.fromisoformat(prop.expires_at)
        delta = (expires - created).total_seconds()
        assert 299 <= delta <= 301

    def test_propose_generates_action_string(self, tmp_path):
        q = self._make_queue(tmp_path=tmp_path)
        prop = q.propose(
            action_type="write_file",
            tool_name="oikos_fs_write",
            reason="test",
            estimated_tokens=0,
            tool_args={"path": "vault/notes.md", "content": "Hello world"},
        )
        assert "oikos_fs_write" in prop.action or "Write" in prop.action
        assert prop.action != ""

    def test_approval_cache_miss(self, tmp_path):
        q = self._make_queue(tmp_path=tmp_path)
        assert q.is_cached("oikos_fs_write", {"path": "x"}, "home") is False

    def test_approval_cache_hit_after_approve(self, tmp_path):
        q = self._make_queue(tmp_path=tmp_path)
        prop = q.propose(
            action_type="write_file",
            tool_name="oikos_fs_write",
            reason="test",
            estimated_tokens=0,
            tool_args={"path": "vault/notes.md"},
            room="home",
        )
        q.approve(prop.proposal_id)
        assert q.is_cached("oikos_fs_write", {"path": "vault/notes.md"}, "home") is True

    def test_approval_cache_scoped_to_room(self, tmp_path):
        q = self._make_queue(tmp_path=tmp_path)
        prop = q.propose(
            action_type="write_file",
            tool_name="oikos_fs_write",
            reason="test",
            estimated_tokens=0,
            tool_args={"path": "vault/notes.md"},
            room="home",
        )
        q.approve(prop.proposal_id)
        # Same tool+args but different room — cache miss
        assert q.is_cached("oikos_fs_write", {"path": "vault/notes.md"}, "work") is False

    def test_expire_stale_auto_rejects(self, tmp_path):
        q = self._make_queue(timeout=0, tmp_path=tmp_path)
        prop = q.propose(
            action_type="write_file",
            tool_name="oikos_fs_write",
            reason="test",
            estimated_tokens=0,
        )
        expired = q.expire_stale()
        assert len(expired) == 1
        assert expired[0].status == "expired"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_approval_ui.py::TestApprovalQueueEnhancements -v`
Expected: FAIL — `room` param not accepted, `is_cached` doesn't exist, `expires_at` not set.

- [ ] **Step 3: Implement queue enhancements**

Replace `core/agency/approval.py` with these changes:

Add to imports:
```python
import hashlib
import time
```

Add module-level helper:
```python
def _make_action(tool_name: str, tool_args: dict) -> str:
    """Generate human-readable action description from tool name and args."""
    path = tool_args.get("path", "")
    content = tool_args.get("content", "")

    if "write" in tool_name and path:
        size = len(content) if isinstance(content, (str, bytes)) else 0
        return f"Write {size} bytes to {path}"
    if "edit" in tool_name and path:
        return f"Edit {path}"
    if "move" in tool_name:
        src = tool_args.get("source", "?")
        dst = tool_args.get("destination", "?")
        return f"Move {src} → {dst}"
    if "copy" in tool_name:
        src = tool_args.get("source", "?")
        dst = tool_args.get("destination", "?")
        return f"Copy {src} → {dst}"
    if "delete" in tool_name and path:
        return f"Delete {path}"
    if "navigate" in tool_name:
        url = tool_args.get("url", "?")
        return f"Navigate to {url}"
    if "gmail" in tool_name or "send" in tool_name:
        to = tool_args.get("to", "?")
        return f"Send email to {to}"
    if "calendar" in tool_name:
        summary = tool_args.get("summary", tool_args.get("title", "event"))
        return f"Calendar: {summary}"

    # Generic fallback
    arg_keys = ", ".join(tool_args.keys()) if tool_args else "no args"
    return f"{tool_name}({arg_keys})"
```

In `ApprovalQueue.__init__`, add:
```python
        self._approval_cache: dict[str, float] = {}
```

In `ApprovalQueue.propose`, add `room` parameter and set new fields:
```python
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
        expires_at = (now + __import__("datetime").timedelta(seconds=self._timeout)).isoformat()
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
```

Add `is_cached` and `_cache_key` methods:
```python
    @staticmethod
    def _cache_key(tool_name: str, tool_args: dict, room: str) -> str:
        import json as _json
        data = _json.dumps({"tool": tool_name, "args": tool_args, "room": room}, sort_keys=True)
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
```

In `approve`, add cache entry after resolve:
```python
    def approve(self, proposal_id: str) -> ActionProposal:
        prop = self._resolve(proposal_id, "approved")
        # Cache: auto-approve same tool+args+room for session
        key = self._cache_key(prop.tool_name, prop.tool_args, prop.room)
        self._approval_cache[key] = time.time() + self._timeout
        return prop
```

Also update `_load` to set new fields from JSONL records:
```python
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
                    room=record.get("room", ""),
                    action=_make_action(record["tool_name"], record.get("tool_args", {})),
                )
```
(Note: `expires_at` isn't stored in JSONL — recalculated on load isn't needed since reloaded proposals are likely already expired.)

- [ ] **Step 4: Fix the timedelta import**

The `propose` method above uses a hacky `__import__`. Clean it up — add `from datetime import datetime, timedelta, timezone` at the top and use `timedelta(seconds=self._timeout)`.

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_approval_ui.py::TestApprovalQueueEnhancements -v`
Expected: PASS

- [ ] **Step 6: Run existing approval tests to verify no regression**

Run: `python -m pytest tests/test_approval.py -v`
Expected: PASS (existing tests should still work — new params have defaults)

- [ ] **Step 7: Commit**

```bash
git add core/agency/approval.py tests/test_approval_ui.py
git commit -m "feat: ApprovalQueue enhancement — room, expires_at, action, approval cache (T-102)"
```

---

## Task 3: Autonomy Middleware Cache Check

**Files:**
- Modify: `core/framework/middleware/autonomy.py`
- Modify: `core/framework/middleware/error_handler.py`
- Test: `tests/test_approval_ui.py`

- [ ] **Step 1: Write failing test for cache bypass**

Append to `tests/test_approval_ui.py`:

```python
class TestAutonomyMiddlewareCache:
    @pytest.fixture
    def middleware_setup(self, tmp_path):
        from core.agency.approval import ApprovalQueue
        from core.agency.autonomy import AutonomyMatrix
        from core.framework.middleware.autonomy import AutonomyMiddleware
        from core.framework.middleware.base import MiddlewareContext
        from core.interface.models import ActionClass
        from dataclasses import dataclass

        @dataclass(frozen=True)
        class FakeMeta:
            name: str = "oikos_fs_write"
            description: str = ""
            privacy: str = "SAFE"
            autonomy: ActionClass = ActionClass.ASK_FIRST
            toolset: str = "file_ops"
            cost_category: str = "local"
            rate_limit: int = 0
            token_ceiling: int = 0

        queue = ApprovalQueue(log_path=tmp_path / "proposals.jsonl")
        mw = AutonomyMiddleware(matrix=None, queue=queue)
        ctx = MiddlewareContext(
            tool_name="oikos_fs_write",
            tool_meta=FakeMeta(),
            arguments={"path": "vault/notes.md", "content": "hello"},
        )
        return mw, queue, ctx

    @pytest.mark.asyncio
    async def test_ask_first_raises_approval_required(self, middleware_setup):
        from core.framework.exceptions import ApprovalRequired

        mw, queue, ctx = middleware_setup

        async def call_next():
            return {"result": "ok"}

        with pytest.raises(ApprovalRequired):
            await mw(ctx, call_next)

    @pytest.mark.asyncio
    async def test_cached_approval_bypasses_queue(self, middleware_setup):
        from core.framework.exceptions import ApprovalRequired

        mw, queue, ctx = middleware_setup

        async def call_next():
            return {"result": "ok"}

        # First call — raises ApprovalRequired
        with pytest.raises(ApprovalRequired) as exc_info:
            await mw(ctx, call_next)

        # Approve the proposal
        queue.approve(exc_info.value.proposal_id)

        # Second call with same args — should auto-approve via cache
        result = await mw(ctx, call_next)
        assert result == {"result": "ok"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_approval_ui.py::TestAutonomyMiddlewareCache -v`
Expected: `test_cached_approval_bypasses_queue` FAIL — middleware doesn't check cache yet.

- [ ] **Step 3: Update autonomy middleware to check cache**

Replace the ASK_FIRST block in `core/framework/middleware/autonomy.py`:

```python
        if level == ActionClass.ASK_FIRST:
            if self._queue is None:
                raise PermissionError(f"Tool '{ctx.tool_name}' requires approval but no queue configured")

            # Check approval cache — auto-approve if same tool+args+room was previously approved
            room_id = ""
            try:
                from core.rooms.manager import get_room_manager
                room_id = get_room_manager().get_active_room().id
            except Exception:
                pass

            if self._queue.is_cached(ctx.tool_name, ctx.arguments, room_id):
                log.info("Auto-approved %s via approval cache (room=%s)", ctx.tool_name, room_id)
                return await call_next()

            proposal = self._queue.propose(
                action_type=ctx.tool_meta.toolset,
                tool_name=ctx.tool_name,
                tool_args=ctx.arguments,
                reason="ASK_FIRST tool invoked via MCP",
                room=room_id,
            )
            raise ApprovalRequired(proposal.proposal_id, ctx.tool_name)
```

- [ ] **Step 4: Update error_handler to include room and action in response**

In `core/framework/middleware/error_handler.py`, update the ApprovalRequired catch block:

```python
        except ApprovalRequired as exc:
            log.info("ASK_FIRST: %s requires approval (proposal: %s)", exc.tool_name, exc.proposal_id)
            return {
                "status": "approval_required",
                "tool": exc.tool_name,
                "proposal_id": exc.proposal_id,
                "message": f"Action requires approval. Tool: {exc.tool_name}, args: {_summarize_args(ctx.arguments)}. Approve via TUI (F9), CLI (oikos approvals), or API. Proposal: {exc.proposal_id}.",
            }
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_approval_ui.py::TestAutonomyMiddlewareCache -v`
Expected: PASS

- [ ] **Step 6: Run existing middleware tests**

Run: `python -m pytest tests/test_framework_middleware_autonomy.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add core/framework/middleware/autonomy.py core/framework/middleware/error_handler.py tests/test_approval_ui.py
git commit -m "feat: approval cache in autonomy middleware — auto-approve on retry (T-102)"
```

---

## Task 4: API Endpoints

**Files:**
- Modify: `core/interface/api/routes/agency.py`
- Modify: `core/interface/api/server.py`
- Test: `tests/test_approval_ui.py`

- [ ] **Step 1: Write failing tests for new API endpoints**

Append to `tests/test_approval_ui.py`:

```python
from fastapi.testclient import TestClient


def _make_test_app():
    """Create a minimal FastAPI app with approval routes for testing."""
    from fastapi import FastAPI
    from core.interface.api.routes.agency import router, _get_queue

    app = FastAPI()
    app.include_router(router, prefix="/api/approvals")

    # Reset queue singleton for test isolation
    import core.interface.api.routes.agency as agency_mod
    agency_mod._queue_instance = None

    return app


class TestApprovalAPI:
    def test_get_pending_returns_list(self, tmp_path):
        app = _make_test_app()
        client = TestClient(app)
        resp = client.get("/api/approvals")
        assert resp.status_code == 200
        body = resp.json()
        assert "pending" in body
        assert isinstance(body["pending"], list)

    def test_get_single_approval(self, tmp_path):
        app = _make_test_app()
        client = TestClient(app)

        # Create a proposal first
        resp = client.post("/api/approvals/propose", json={
            "action_type": "write_file",
            "tool_name": "oikos_fs_write",
            "reason": "test",
            "tool_args": {"path": "vault/notes.md", "content": "hello"},
        })
        assert resp.status_code == 201
        proposal_id = resp.json()["id"]

        # Fetch it
        resp = client.get(f"/api/approvals/{proposal_id}")
        assert resp.status_code == 200
        assert resp.json()["id"] == proposal_id
        assert resp.json()["action"] != ""
        assert resp.json()["expires_at"] is not None

    def test_approve_and_reject(self, tmp_path):
        app = _make_test_app()
        client = TestClient(app)

        # Create two proposals
        r1 = client.post("/api/approvals/propose", json={
            "action_type": "write_file", "tool_name": "oikos_fs_write",
            "reason": "test1", "tool_args": {"path": "a.md"},
        })
        r2 = client.post("/api/approvals/propose", json={
            "action_type": "write_file", "tool_name": "oikos_fs_write",
            "reason": "test2", "tool_args": {"path": "b.md"},
        })
        id1 = r1.json()["id"]
        id2 = r2.json()["id"]

        # Approve first
        resp = client.post(f"/api/approvals/{id1}/approve")
        assert resp.status_code == 200
        assert resp.json()["status"] == "approved"

        # Reject second
        resp = client.post(f"/api/approvals/{id2}/reject", json={"reason": "not needed"})
        assert resp.status_code == 200
        assert resp.json()["status"] == "rejected"

    def test_dismiss_approval(self, tmp_path):
        app = _make_test_app()
        client = TestClient(app)

        r = client.post("/api/approvals/propose", json={
            "action_type": "write_file", "tool_name": "oikos_fs_write",
            "reason": "test", "tool_args": {},
        })
        pid = r.json()["id"]

        resp = client.delete(f"/api/approvals/{pid}")
        assert resp.status_code == 200

        # Should no longer appear in pending
        pending = client.get("/api/approvals").json()["pending"]
        assert all(p["id"] != pid for p in pending)

    def test_approve_unknown_returns_404(self, tmp_path):
        app = _make_test_app()
        client = TestClient(app)
        resp = client.post("/api/approvals/nonexistent/approve")
        assert resp.status_code == 404

    def test_response_shape_matches_spec(self, tmp_path):
        app = _make_test_app()
        client = TestClient(app)

        r = client.post("/api/approvals/propose", json={
            "action_type": "write_file", "tool_name": "oikos_fs_write",
            "reason": "test",
            "tool_args": {"path": "vault/notes.md", "content": "A" * 300},
        })
        pid = r.json()["id"]

        resp = client.get(f"/api/approvals/{pid}")
        body = resp.json()

        # Verify dispatch-specified response shape
        assert "id" in body
        assert "tool_name" in body
        assert "action" in body
        assert "risk_level" in body
        assert "requested_at" in body
        assert "arguments" in body
        assert "room" in body
        assert "expires_at" in body
        # Content should be previewed, not full
        if "content_preview" in body["arguments"]:
            assert len(body["arguments"]["content_preview"]) <= 203  # 200 + "..."
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_approval_ui.py::TestApprovalAPI -v`
Expected: FAIL — endpoints don't exist yet, response shape doesn't match.

- [ ] **Step 3: Rewrite agency.py routes**

Replace `core/interface/api/routes/agency.py`:

```python
"""Approval endpoints — list, review, approve, reject, dismiss pending actions."""

from __future__ import annotations

import json

from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel

from core.autonomic.events import emit_event

router = APIRouter()


# ── Dependency ───────────────────────────────────────────────────────

_queue_instance = None


def _get_queue():
    global _queue_instance
    if _queue_instance is None:
        from core.agency.approval import ApprovalQueue
        _queue_instance = ApprovalQueue()
    return _queue_instance


# ── Request models ───────────────────────────────────────────────────

class ProposeRequest(BaseModel):
    action_type: str
    tool_name: str
    tool_args: dict = {}
    reason: str
    estimated_tokens: int = 0
    risk_level: str = "low"
    room: str = ""


class RejectRequest(BaseModel):
    reason: str | None = None


# ── Response serialization ───────────────────────────────────────────

def _serialize(prop) -> dict:
    """Transform ActionProposal to dispatch-specified response shape."""
    args = dict(prop.tool_args)
    if "content" in args:
        content = args.pop("content")
        preview = content[:200] + "..." if len(str(content)) > 200 else content
        args["content_preview"] = preview
    return {
        "id": prop.proposal_id,
        "tool_name": prop.tool_name,
        "action": prop.action,
        "risk_level": prop.risk_level,
        "requested_at": prop.created_at,
        "arguments": args,
        "room": prop.room,
        "expires_at": prop.expires_at,
        "status": prop.status,
    }


# ── Endpoints ────────────────────────────────────────────────────────

@router.get("")
def list_pending(queue=Depends(_get_queue)):
    """List all pending approval requests."""
    queue.expire_stale()
    return {"pending": [_serialize(p) for p in queue.list_pending()]}


@router.get("/{proposal_id}")
def get_approval(proposal_id: str, queue=Depends(_get_queue)):
    """Get details of a specific approval request."""
    queue.expire_stale()
    proposals = queue._proposals
    if proposal_id not in proposals:
        raise HTTPException(status_code=404, detail=f"Proposal {proposal_id!r} not found")
    return _serialize(proposals[proposal_id])


@router.post("/propose", status_code=201)
def propose_action(req: ProposeRequest, queue=Depends(_get_queue)):
    serialized = json.dumps(req.tool_args, default=str)
    if len(serialized.encode()) > 4096:
        raise HTTPException(status_code=413, detail="tool_args exceeds 4096-byte limit")

    from pathlib import Path
    from core.agency.autonomy import AutonomyMatrix
    from core.interface.models import ActionClass

    matrix = AutonomyMatrix(Path("autonomy_matrix.json"))
    classification = matrix.classify(req.action_type)
    if classification == ActionClass.PROHIBITED:
        raise HTTPException(status_code=403, detail=f"Action type {req.action_type!r} is PROHIBITED")

    prop = queue.propose(
        action_type=req.action_type,
        tool_name=req.tool_name,
        tool_args=req.tool_args,
        reason=req.reason,
        estimated_tokens=req.estimated_tokens,
        risk_level="low" if classification == ActionClass.SAFE else "medium",
        room=req.room,
    )
    emit_event("agency", "proposal_created", {
        "proposal_id": prop.proposal_id,
        "action_type": req.action_type,
        "tool_name": req.tool_name,
    })
    return _serialize(prop)


@router.post("/{proposal_id}/approve")
def approve_action(proposal_id: str, queue=Depends(_get_queue)):
    try:
        prop = queue.approve(proposal_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Proposal {proposal_id!r} not found")
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    emit_event("agency", "proposal_approved", {"proposal_id": proposal_id})
    return _serialize(prop)


@router.post("/{proposal_id}/reject")
def reject_action(
    proposal_id: str,
    req: RejectRequest | None = Body(None),
    queue=Depends(_get_queue),
):
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
    return _serialize(prop)


@router.delete("/{proposal_id}")
def dismiss_action(proposal_id: str, queue=Depends(_get_queue)):
    """Dismiss without action — expires the request."""
    try:
        prop = queue.reject(proposal_id, reason="dismissed")
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Proposal {proposal_id!r} not found")
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    emit_event("agency", "proposal_dismissed", {"proposal_id": proposal_id})
    return _serialize(prop)
```

- [ ] **Step 4: Update server.py prefix**

In `core/interface/api/server.py`, change the agency router line:

```python
    # was: app.include_router(agency_router, prefix="/api/agency", dependencies=auth_dep)
    app.include_router(agency_router, prefix="/api/approvals", dependencies=auth_dep)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_approval_ui.py::TestApprovalAPI -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add core/interface/api/routes/agency.py core/interface/api/server.py tests/test_approval_ui.py
git commit -m "feat: approval API endpoints with dispatch-specified response shape (T-102)"
```

---

## Task 5: TUI Client Methods

**Files:**
- Modify: `core/interface/tui/client.py`
- Test: `tests/test_approval_ui.py`

- [ ] **Step 1: Write failing test for client methods**

Append to `tests/test_approval_ui.py`:

```python
class TestOikOSClientApprovals:
    @pytest.mark.asyncio
    async def test_pending_approvals(self):
        from core.interface.tui.client import OikOSClient

        client = OikOSClient()
        # Method should exist (will fail on connection, but we're testing interface)
        assert hasattr(client, "pending_approvals")
        await client.close()

    @pytest.mark.asyncio
    async def test_approve_method_exists(self):
        from core.interface.tui.client import OikOSClient

        client = OikOSClient()
        assert hasattr(client, "approval_approve")
        assert hasattr(client, "approval_reject")
        assert hasattr(client, "approval_dismiss")
        await client.close()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_approval_ui.py::TestOikOSClientApprovals -v`
Expected: FAIL — methods don't exist.

- [ ] **Step 3: Add approval methods to OikOSClient**

Add to `core/interface/tui/client.py` (in the OikOSClient class, before `close`):

```python
    async def pending_approvals(self) -> list[dict]:
        """GET /api/approvals — returns list of pending approval requests."""
        data = await self._get("/api/approvals", fallback={"pending": []})
        return data.get("pending", [])

    async def approval_detail(self, proposal_id: str) -> dict:
        """GET /api/approvals/{id}."""
        return await self._get(f"/api/approvals/{proposal_id}")

    async def approval_approve(self, proposal_id: str) -> dict:
        """POST /api/approvals/{id}/approve."""
        try:
            r = await self._client.post(f"/api/approvals/{proposal_id}/approve")
            if r.status_code == 200:
                return r.json()
        except (httpx.ConnectError, httpx.TimeoutException):
            pass
        return {}

    async def approval_reject(self, proposal_id: str, reason: str | None = None) -> dict:
        """POST /api/approvals/{id}/reject."""
        body = {"reason": reason} if reason else None
        try:
            r = await self._client.post(f"/api/approvals/{proposal_id}/reject", json=body)
            if r.status_code == 200:
                return r.json()
        except (httpx.ConnectError, httpx.TimeoutException):
            pass
        return {}

    async def approval_dismiss(self, proposal_id: str) -> dict:
        """DELETE /api/approvals/{id}."""
        try:
            r = await self._client.delete(f"/api/approvals/{proposal_id}")
            if r.status_code == 200:
                return r.json()
        except (httpx.ConnectError, httpx.TimeoutException):
            pass
        return {}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_approval_ui.py::TestOikOSClientApprovals -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add core/interface/tui/client.py tests/test_approval_ui.py
git commit -m "feat: TUI client approval methods (T-102)"
```

---

## Task 6: TUI Approval Notification Bar

**Files:**
- Create: `core/interface/tui/widgets/approval_bar.py`
- Modify: `core/interface/tui/app.py`
- Modify: `core/interface/tui/styles.tcss`
- Test: `tests/test_approval_ui.py`

- [ ] **Step 1: Write failing test for ApprovalBar widget**

Append to `tests/test_approval_ui.py`:

```python
class TestApprovalBar:
    def test_widget_exists(self):
        from core.interface.tui.widgets.approval_bar import ApprovalBar
        bar = ApprovalBar()
        assert bar.id == "approval-bar"

    def test_update_with_pending(self):
        from core.interface.tui.widgets.approval_bar import ApprovalBar
        bar = ApprovalBar()
        bar.update_pending([
            {"id": "abc123", "tool_name": "oikos_fs_write", "action": "Write 100 bytes to notes.md"},
        ])
        assert bar._count == 1

    def test_update_with_empty(self):
        from core.interface.tui.widgets.approval_bar import ApprovalBar
        bar = ApprovalBar()
        bar.update_pending([])
        assert bar._count == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_approval_ui.py::TestApprovalBar -v`
Expected: FAIL — module doesn't exist.

- [ ] **Step 3: Create ApprovalBar widget**

Create `core/interface/tui/widgets/approval_bar.py`:

```python
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
            self.update(f"\u26a0 {self._count} ACTIONS PENDING: {action} (+{self._count - 1} more) [F9 to review]")
```

- [ ] **Step 4: Add ApprovalBar to app.py compose and polling**

In `core/interface/tui/app.py`, add import:
```python
from core.interface.tui.widgets.approval_bar import ApprovalBar
```

In `compose()`, add ApprovalBar between content-area and footer:
```python
    def compose(self) -> ComposeResult:
        yield OikOSHeader()
        with Horizontal(id="content-area"):
            yield OikOSSidebar()
            with ContentSwitcher(initial="lobby", id="content-switcher"):
                yield LobbyView(id="lobby")
                yield ChatView(id="chat")
                yield VaultView(id="vault")
                yield RoomsView(id="rooms")
                yield SettingsView(id="settings")
                yield TasksView(id="tasks")
                yield AgentsView(id="agents")
        yield ApprovalBar()
        yield OikOSFooter()
```

In `on_mount()`, add polling timer:
```python
        self.set_interval(3, self._poll_approvals)
```

Add polling method:
```python
    async def _poll_approvals(self) -> None:
        """Poll for pending approval requests every 3 seconds."""
        try:
            pending = await self.api_client.pending_approvals()
            self.query_one(ApprovalBar).update_pending(pending)
        except Exception:
            pass  # API may not be ready
```

- [ ] **Step 5: Add CSS for ApprovalBar**

Add to `core/interface/tui/styles.tcss`:

```tcss
/* ── Approval bar ──────────────────────────────────────────────── */

ApprovalBar {
    dock: bottom;
    height: 1;
    background: #1A1400;
    color: #FFB000;
    padding: 0 1;
    display: none;
}

Screen.theme-green ApprovalBar {
    background: #001A00;
    color: #33FF33;
}

Screen.theme-white ApprovalBar {
    background: #1A1A1A;
    color: #E0E0E0;
}
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `python -m pytest tests/test_approval_ui.py::TestApprovalBar -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add core/interface/tui/widgets/approval_bar.py core/interface/tui/app.py core/interface/tui/styles.tcss tests/test_approval_ui.py
git commit -m "feat: TUI approval notification bar with 3-second polling (T-102)"
```

---

## Task 7: TUI Approval Modal (F9)

**Files:**
- Create: `core/interface/tui/views/approvals.py`
- Modify: `core/interface/tui/app.py`
- Modify: `core/interface/tui/styles.tcss`
- Test: `tests/test_approval_ui.py`

- [ ] **Step 1: Write failing test for ApprovalModal**

Append to `tests/test_approval_ui.py`:

```python
class TestApprovalModal:
    def test_modal_class_exists(self):
        from core.interface.tui.views.approvals import ApprovalModal
        assert ApprovalModal is not None

    def test_modal_has_bindings(self):
        from core.interface.tui.views.approvals import ApprovalModal
        actions = [b.action for b in ApprovalModal.BINDINGS]
        assert "approve_selected" in actions
        assert "reject_selected" in actions or "dismiss" in actions
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_approval_ui.py::TestApprovalModal -v`
Expected: FAIL — module doesn't exist.

- [ ] **Step 3: Create ApprovalModal screen**

Create `core/interface/tui/views/approvals.py`:

```python
"""Approval modal — F9 screen for reviewing and acting on pending approvals."""
from __future__ import annotations

from datetime import datetime

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Static, ListView, ListItem


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
        width: 70;
        height: 20;
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

    .approval-item-selected {
        color: #FFB000;
        background: #1A1400;
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
        # Arguments
        args = p.get("arguments", {})
        for k, v in list(args.items())[:5]:
            val = str(v)[:60]
            lines.append(f"  {k}: {val}")
        # Expiry
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
            detail = self.query_one("#approval-detail", Static)
            detail.update(self._format_detail(self._pending[idx]))

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
```

- [ ] **Step 4: Add F9 binding to app.py**

In `core/interface/tui/app.py`, add to BINDINGS:
```python
        Binding("f9", "show_approvals", "Approvals", show=False),
```

Add the action method:
```python
    async def action_show_approvals(self) -> None:
        """Open the approval review modal (F9)."""
        pending = await self.api_client.pending_approvals()
        from core.interface.tui.views.approvals import ApprovalModal
        await self.push_screen(ApprovalModal(pending))
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_approval_ui.py::TestApprovalModal -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add core/interface/tui/views/approvals.py core/interface/tui/app.py tests/test_approval_ui.py
git commit -m "feat: TUI approval modal — F9 opens review panel with approve/reject (T-102)"
```

---

## Task 8: CLI Commands

**Files:**
- Modify: `core/interface/cli.py`
- Test: `tests/test_approval_ui.py`

- [ ] **Step 1: Write failing test for CLI commands**

Append to `tests/test_approval_ui.py`:

```python
from click.testing import CliRunner


class TestApprovalCLI:
    def test_approvals_list_command_exists(self):
        from core.interface.cli import main

        runner = CliRunner()
        result = runner.invoke(main, ["approvals"])
        # Should not be "Error: No such command"
        assert "No such command" not in (result.output or "")

    def test_approve_command_exists(self):
        from core.interface.cli import main

        runner = CliRunner()
        result = runner.invoke(main, ["approve", "--help"])
        assert "No such command" not in (result.output or "")

    def test_reject_command_exists(self):
        from core.interface.cli import main

        runner = CliRunner()
        result = runner.invoke(main, ["reject", "--help"])
        assert "No such command" not in (result.output or "")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_approval_ui.py::TestApprovalCLI -v`
Expected: FAIL — commands don't exist.

- [ ] **Step 3: Add CLI commands**

Add to `core/interface/cli.py`:

```python
@main.command("approvals")
def approvals_list():
    """List pending approval requests."""
    from core.agency.approval import ApprovalQueue

    queue = ApprovalQueue()
    queue.expire_stale()
    pending = queue.list_pending()

    if not pending:
        console.print("[#6B5012]No pending approvals.[/]")
        return

    from rich.table import Table

    table = Table(show_lines=False, box=None, padding=(0, 2))
    table.add_column("ID", style="#6B5012", width=10)
    table.add_column("Tool", style="#D4A017")
    table.add_column("Action", style="#FFB000")
    table.add_column("Room", style="#6B5012")
    for p in pending:
        table.add_row(p.proposal_id, p.tool_name, p.action, p.room or "default")

    console.print(table)
    console.print(f"\n[#6B5012]{len(pending)} pending. Use [#D4A017]oikos approve <id>[/] or [#D4A017]oikos reject <id>[/].[/]")


@main.command("approve")
@click.argument("proposal_id")
def approve_cmd(proposal_id: str):
    """Approve a pending action by proposal ID."""
    from core.agency.approval import ApprovalQueue

    queue = ApprovalQueue()
    try:
        prop = queue.approve(proposal_id)
        console.print(f"[#33FF33]\u2713[/] Approved: {prop.action or prop.tool_name}")
    except KeyError:
        console.print(f"[#FF3333]Proposal {proposal_id!r} not found.[/]")
        raise SystemExit(1)
    except ValueError as e:
        console.print(f"[#FF3333]{e}[/]")
        raise SystemExit(1)


@main.command("reject")
@click.argument("proposal_id")
@click.option("--reason", "-r", default=None, help="Rejection reason")
def reject_cmd(proposal_id: str, reason: str | None):
    """Reject a pending action by proposal ID."""
    from core.agency.approval import ApprovalQueue

    queue = ApprovalQueue()
    try:
        prop = queue.reject(proposal_id, reason=reason)
        console.print(f"[#FF3333]\u2717[/] Rejected: {prop.action or prop.tool_name}")
    except KeyError:
        console.print(f"[#FF3333]Proposal {proposal_id!r} not found.[/]")
        raise SystemExit(1)
    except ValueError as e:
        console.print(f"[#FF3333]{e}[/]")
        raise SystemExit(1)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_approval_ui.py::TestApprovalCLI -v`
Expected: PASS

- [ ] **Step 5: Run all T-102 tests**

Run: `python -m pytest tests/test_approval_ui.py -v`
Expected: All PASS

- [ ] **Step 6: Run full test suite for regression**

Run: `python -m pytest tests/ -x -q --timeout=30`
Expected: No regressions (existing ~1,671 tests pass)

- [ ] **Step 7: Commit**

```bash
git add core/interface/cli.py tests/test_approval_ui.py
git commit -m "feat: CLI approval commands — oikos approvals/approve/reject (T-102)"
```

---

## Task 9: Integration Verification

- [ ] **Step 1: Run full test suite**

```bash
python -m pytest tests/ -x -q --timeout=30
```

Expected: All pass, no regressions.

- [ ] **Step 2: Verify dispatch criteria checklist**

| # | Criterion | How to verify |
|---|---|---|
| 1 | GET /api/approvals returns pending | `TestApprovalAPI::test_get_pending_returns_list` |
| 2 | POST approve triggers execution | `TestApprovalAPI::test_approve_and_reject` + cache test |
| 3 | POST reject returns rejection | `TestApprovalAPI::test_approve_and_reject` |
| 4 | Requests expire after 5 min | `TestApprovalQueueEnhancements::test_expire_stale_auto_rejects` |
| 5 | TUI notification bar on any screen | `TestApprovalBar` + polling in app |
| 6 | F9 opens approval detail panel | `TestApprovalModal` + F9 binding |
| 7 | TUI approve executes tool | Modal `action_approve_selected` → API → cache |
| 8 | TUI reject returns rejection | Modal `action_reject_selected` → API |
| 9 | CLI commands work | `TestApprovalCLI` |
| 10 | Sensitive args redacted | `_serialize` content_preview truncation |
| 11 | Multiple simultaneous requests | Queue is a dict, not single slot |
| 12 | Google write triggers flow | Same middleware path (ASK_FIRST tools) |
| 13 | File write triggers flow | Same middleware path (ASK_FIRST tools) |
| 14 | Existing tests pass | Full suite run |
| 15 | Minimum 15 new tests | Count tests in test_approval_ui.py |

- [ ] **Step 3: Final commit — update docs**

Update CLAUDE.md test count and add T-102 to shipped section. Commit:

```bash
git commit -m "docs: update CLAUDE.md with T-102 Approval UI (shipped)"
```
