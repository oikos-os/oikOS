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


class TestAutonomyMiddlewareCache:
    @pytest.fixture
    def middleware_setup(self, tmp_path):
        from dataclasses import dataclass

        from core.agency.approval import ApprovalQueue
        from core.framework.middleware.autonomy import AutonomyMiddleware
        from core.interface.models import ActionClass

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

        from core.framework.middleware.base import MiddlewareContext

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


class TestApprovalAPI:
    def _make_test_app(self):
        """Create a minimal FastAPI app with approval routes for testing."""
        from fastapi import FastAPI

        from core.interface.api.routes.agency import router

        app = FastAPI()
        app.include_router(router, prefix="/api/approvals")

        # Reset queue singleton for test isolation
        import core.interface.api.routes.agency as agency_mod
        agency_mod._queue_instance = None

        return app

    def test_get_pending_returns_list(self):
        from fastapi.testclient import TestClient

        app = self._make_test_app()
        client = TestClient(app)
        resp = client.get("/api/approvals")
        assert resp.status_code == 200
        body = resp.json()
        assert "pending" in body
        assert isinstance(body["pending"], list)

    def test_get_single_approval(self):
        from fastapi.testclient import TestClient

        app = self._make_test_app()
        client = TestClient(app)

        resp = client.post("/api/approvals/propose", json={
            "action_type": "write_file",
            "tool_name": "oikos_fs_write",
            "reason": "test",
            "tool_args": {"path": "vault/notes.md", "content": "hello"},
        })
        assert resp.status_code == 201
        proposal_id = resp.json()["id"]

        resp = client.get(f"/api/approvals/{proposal_id}")
        assert resp.status_code == 200
        assert resp.json()["id"] == proposal_id
        assert resp.json()["action"] != ""
        assert resp.json()["expires_at"] is not None

    def test_approve_and_reject(self):
        from fastapi.testclient import TestClient

        app = self._make_test_app()
        client = TestClient(app)

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

        resp = client.post(f"/api/approvals/{id1}/approve")
        assert resp.status_code == 200
        assert resp.json()["status"] == "approved"

        resp = client.post(f"/api/approvals/{id2}/reject", json={"reason": "not needed"})
        assert resp.status_code == 200
        assert resp.json()["status"] == "rejected"

    def test_dismiss_approval(self):
        from fastapi.testclient import TestClient

        app = self._make_test_app()
        client = TestClient(app)

        r = client.post("/api/approvals/propose", json={
            "action_type": "write_file", "tool_name": "oikos_fs_write",
            "reason": "test", "tool_args": {},
        })
        pid = r.json()["id"]

        resp = client.delete(f"/api/approvals/{pid}")
        assert resp.status_code == 200

        pending = client.get("/api/approvals").json()["pending"]
        assert all(p["id"] != pid for p in pending)

    def test_approve_unknown_returns_404(self):
        from fastapi.testclient import TestClient

        app = self._make_test_app()
        client = TestClient(app)
        resp = client.post("/api/approvals/nonexistent/approve")
        assert resp.status_code == 404

    def test_response_shape_matches_spec(self):
        from fastapi.testclient import TestClient

        app = self._make_test_app()
        client = TestClient(app)

        r = client.post("/api/approvals/propose", json={
            "action_type": "write_file", "tool_name": "oikos_fs_write",
            "reason": "test",
            "tool_args": {"path": "vault/notes.md", "content": "A" * 300},
        })
        pid = r.json()["id"]

        resp = client.get(f"/api/approvals/{pid}")
        body = resp.json()

        assert "id" in body
        assert "tool_name" in body
        assert "action" in body
        assert "risk_level" in body
        assert "requested_at" in body
        assert "arguments" in body
        assert "room" in body
        assert "expires_at" in body
        if "content_preview" in body["arguments"]:
            assert len(body["arguments"]["content_preview"]) <= 203


class TestApprovalCLI:
    def test_approvals_lists_via_api(self):
        from unittest.mock import MagicMock, patch

        from click.testing import CliRunner
        from core.interface.cli import main

        mock_resp = MagicMock()
        mock_resp.json.return_value = {"pending": []}
        with patch("httpx.get", return_value=mock_resp):
            runner = CliRunner()
            result = runner.invoke(main, ["approvals"])
            assert "No such command" not in (result.output or "")
            assert result.exit_code == 0

    def test_approve_routes_through_api(self):
        from unittest.mock import MagicMock, patch

        from click.testing import CliRunner
        from core.interface.cli import main

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"action": "Write 10 bytes to test.md", "tool_name": "fs_write"}
        with patch("httpx.post", return_value=mock_resp) as mock_post:
            runner = CliRunner()
            result = runner.invoke(main, ["approve", "abc123"])
            assert result.exit_code == 0
            mock_post.assert_called_once()
            assert "/api/approvals/abc123/approve" in mock_post.call_args[0][0]

    def test_reject_routes_through_api(self):
        from unittest.mock import MagicMock, patch

        from click.testing import CliRunner
        from core.interface.cli import main

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"action": "Write 10 bytes to test.md", "tool_name": "fs_write"}
        with patch("httpx.post", return_value=mock_resp) as mock_post:
            runner = CliRunner()
            result = runner.invoke(main, ["reject", "abc123", "-r", "not now"])
            assert result.exit_code == 0
            mock_post.assert_called_once()
            assert "/api/approvals/abc123/reject" in mock_post.call_args[0][0]

    def test_approve_server_down_shows_error(self):
        from unittest.mock import patch

        import httpx
        from click.testing import CliRunner
        from core.interface.cli import main

        with patch("httpx.post", side_effect=httpx.ConnectError("")):
            runner = CliRunner()
            result = runner.invoke(main, ["approve", "abc123"])
            assert result.exit_code == 1
            assert "Server not running" in (result.output or "")


class TestApprovalModal:
    def test_modal_class_exists(self):
        from core.interface.tui.views.approvals import ApprovalModal

        assert ApprovalModal is not None

    def test_modal_has_bindings(self):
        from core.interface.tui.views.approvals import ApprovalModal

        actions = [b.action for b in ApprovalModal.BINDINGS]
        assert "approve_selected" in actions
        assert "reject_selected" in actions

    def test_modal_formats_items(self):
        from core.interface.tui.views.approvals import ApprovalModal

        modal = ApprovalModal([
            {"id": "abc", "tool_name": "oikos_fs_write", "action": "Write 100 bytes to notes.md",
             "room": "home", "risk_level": "ASK_FIRST", "arguments": {"path": "notes.md"},
             "expires_at": "2026-12-31T00:00:00+00:00"},
        ])
        assert modal._pending[0]["tool_name"] == "oikos_fs_write"

    def test_modal_empty_pending(self):
        from core.interface.tui.views.approvals import ApprovalModal

        modal = ApprovalModal([])
        assert modal._pending == []


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

    def test_multiple_pending_shows_count(self):
        from core.interface.tui.widgets.approval_bar import ApprovalBar

        bar = ApprovalBar()
        bar.update_pending([
            {"id": "a", "tool_name": "oikos_fs_write", "action": "Write a.md"},
            {"id": "b", "tool_name": "oikos_fs_edit", "action": "Edit b.md"},
        ])
        assert bar._count == 2


class TestOikOSClientApprovals:
    @pytest.mark.asyncio
    async def test_client_has_approval_methods(self):
        from core.interface.tui.client import OikOSClient

        client = OikOSClient()
        assert hasattr(client, "pending_approvals")
        assert hasattr(client, "approval_approve")
        assert hasattr(client, "approval_reject")
        assert hasattr(client, "approval_dismiss")
        await client.close()


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
        assert prop.action != ""
        assert "Write" in prop.action

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
        assert q.is_cached("oikos_fs_write", {"path": "vault/notes.md"}, "work") is False

    def test_expire_stale_auto_rejects(self, tmp_path):
        q = self._make_queue(timeout=0, tmp_path=tmp_path)
        q.propose(
            action_type="write_file",
            tool_name="oikos_fs_write",
            reason="test",
            estimated_tokens=0,
        )
        expired = q.expire_stale()
        assert len(expired) == 1
        assert expired[0].status == "expired"
