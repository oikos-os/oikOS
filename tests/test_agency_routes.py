from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def app(tmp_path):
    """Create test app with agency routes."""
    from fastapi import FastAPI
    from core.interface.api.routes.agency import router, _get_queue
    from core.agency.approval import ApprovalQueue

    app = FastAPI()
    log_path = tmp_path / "proposals.jsonl"
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

    def test_approve_already_resolved_returns_409(self, app):
        app_instance, queue = app
        client = TestClient(app_instance)
        prop = queue.propose(action_type="write_file", tool_name="fw", reason="r", estimated_tokens=0)
        queue.approve(prop.proposal_id)
        resp = client.post(f"/api/agency/approve/{prop.proposal_id}")
        assert resp.status_code == 409

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

    def test_reject_unknown_returns_404(self, app):
        app_instance, _ = app
        client = TestClient(app_instance)
        resp = client.post("/api/agency/reject/nonexistent")
        assert resp.status_code == 404

    def test_reject_already_resolved_returns_409(self, app):
        app_instance, queue = app
        client = TestClient(app_instance)
        prop = queue.propose(action_type="write_file", tool_name="fw", reason="r", estimated_tokens=0)
        queue.reject(prop.proposal_id)
        resp = client.post(f"/api/agency/reject/{prop.proposal_id}")
        assert resp.status_code == 409

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
