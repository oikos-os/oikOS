"""API endpoint tests — all core functions mocked, no Ollama/LanceDB needed."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from core.interface.api.server import create_app


@pytest.fixture
def client():
    return TestClient(create_app())


@pytest.fixture
def dev_client():
    return TestClient(create_app(dev=True))


# ── System ───────────────────────────────────────────────────────────

@patch("core.autonomic.fsm.get_last_transition_time", return_value="2026-03-02T12:00:00")
@patch("core.autonomic.fsm.get_current_state")
def test_get_state(mock_state, mock_time, client):
    from core.interface.models import SystemState
    mock_state.return_value = SystemState.ACTIVE
    r = client.get("/api/state")
    assert r.status_code == 200
    data = r.json()
    assert data["fsm_state"] == "active"
    assert "version" in data
    assert "uptime" in data


@patch("core.autonomic.daemon.get_status")
@patch("core.memory.embedder.check_health", return_value=True)
def test_get_health(mock_health, mock_status, client):
    mock_status.return_value = {"running": True, "pid": 1234, "fsm_state": "active",
                                 "vram_yielded": False, "health_failures": 0, "uptime_seconds": 100}
    r = client.get("/api/health")
    assert r.status_code == 200
    assert "running" in r.json()


@patch("core.safety.credits.load_credits")
def test_get_credits(mock_credits, client):
    mock_bal = MagicMock()
    mock_bal.model_dump.return_value = {"monthly_cap": 1000000, "used": 500, "remaining": 999500,
                                         "last_reset": "2026-03-01", "in_deficit": False, "deficit": 0}
    mock_credits.return_value = mock_bal
    r = client.get("/api/credits")
    assert r.status_code == 200
    assert r.json()["monthly_cap"] == 1000000


def test_get_config(client):
    r = client.get("/api/config")
    assert r.status_code == 200
    data = r.json()
    assert "version" in data
    for v in data.values():
        if isinstance(v, str):
            assert "\\" not in v or ":" not in v


# ── Chat ─────────────────────────────────────────────────────────────

@patch("core.cognition.handler.execute_query_stream")
def test_chat_sse(mock_stream, client):
    mock_resp = MagicMock()
    mock_resp.route.value = "local"
    mock_resp.model_used = "qwen2.5:14b"
    mock_resp.confidence = 85.0
    mock_resp.pii_scrubbed = False
    mock_resp.routing_decision.pii_detected = False
    mock_resp.routing_decision.cosine_gate_fired = False
    mock_resp.contradiction = None

    mock_stream.return_value = iter([
        {"delta": "Hello", "done": False, "response": None},
        {"delta": " world", "done": False, "response": None},
        {"delta": "", "done": True, "response": mock_resp},
    ])

    r = client.post("/api/chat", json={"query": "test"})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    lines = [l for l in r.text.split("\n") if l.startswith("data: ")]
    assert len(lines) == 3
    first = json.loads(lines[0].removeprefix("data: "))
    assert first["delta"] == "Hello"
    last = json.loads(lines[-1].removeprefix("data: "))
    assert last["done"] is True


@patch("core.memory.session.list_recent_sessions", return_value=[{"session_id": "abc", "started_at": "2026-03-02T00:00:00"}])
def test_chat_history(mock_list, client):
    r = client.get("/api/chat/history")
    assert r.status_code == 200
    assert isinstance(r.json(), list)
    assert r.json()[0]["session_id"] == "abc"


@patch("core.memory.session.load_session_transcript", return_value=[])
def test_chat_session_nonexistent(mock_load, client):
    r = client.get("/api/chat/session/nonexistent")
    assert r.status_code == 200
    assert r.json() == []


# ── Vault ────────────────────────────────────────────────────────────

@patch("core.memory.indexer.get_table_stats", return_value={"total_rows": 100, "unique_files": 10, "tier_breakdown": {}})
def test_vault_stats(mock_stats, client):
    r = client.get("/api/vault/stats")
    assert r.status_code == 200
    assert r.json()["total_rows"] == 100


@patch("core.memory.search.hybrid_search")
def test_vault_search(mock_search, client):
    mock_result = MagicMock()
    mock_result.content = "test content"
    mock_result.source_path = "vault/knowledge/test.md"
    mock_result.header_path = "Test > Section"
    mock_result.tier.value = "semantic"
    mock_result.final_score = 0.9
    mock_search.return_value = [mock_result]

    r = client.get("/api/vault/search?q=test")
    assert r.status_code == 200
    assert isinstance(r.json(), list)
    assert r.json()[0]["tier"] == "semantic"


# ── Agents ───────────────────────────────────────────────────────────

@patch("core.agency.consolidation.load_pending_proposals", return_value=[])
def test_consolidation_proposals(mock_proposals, client):
    r = client.get("/api/agents/consolidation/proposals")
    assert r.status_code == 200
    assert r.json() == []


@patch("core.interface.api.routes.agents._read_last_jsonl_line", return_value={"total": 10, "passed": 10})
def test_gauntlet_latest(mock_read, client):
    r = client.get("/api/agents/gauntlet/latest")
    assert r.status_code == 200


# ── WebSocket ────────────────────────────────────────────────────────

@patch("core.autonomic.daemon.get_status")
@patch("core.autonomic.fsm.get_current_state")
def test_ws_heartbeat(mock_state, mock_status, client):
    from core.interface.models import SystemState
    mock_state.return_value = SystemState.ACTIVE
    mock_status.return_value = {"running": True, "pid": 1, "fsm_state": "active",
                                 "vram_yielded": False, "health_failures": 0, "uptime_seconds": 10}
    with client.websocket_connect("/ws/heartbeat") as ws:
        data = json.loads(ws.receive_text())
        assert data["fsm_state"] == "active"
        assert "daemon" in data


# ── CORS ─────────────────────────────────────────────────────────────

def test_cors_disabled_prod(client):
    r = client.options("/api/state", headers={"Origin": "http://localhost:5173",
                                               "Access-Control-Request-Method": "GET"})
    assert "access-control-allow-origin" not in r.headers


@patch("core.autonomic.fsm.get_last_transition_time", return_value=None)
@patch("core.autonomic.fsm.get_current_state")
def test_cors_enabled_dev(mock_state, mock_time, dev_client):
    from core.interface.models import SystemState
    mock_state.return_value = SystemState.ACTIVE
    r = dev_client.get("/api/state", headers={"Origin": "http://localhost:5173"})
    assert r.headers.get("access-control-allow-origin") == "http://localhost:5173"


# ── Auth ────────────────────────────────────────────────────────────

def test_auth_rejects_wrong_key(monkeypatch):
    monkeypatch.setenv("OIKOS_API_KEY", "correct-key-123")
    client = TestClient(create_app())
    r = client.get("/api/config", headers={"X-API-Key": "wrong-key"})
    assert r.status_code == 401


def test_auth_accepts_correct_key(monkeypatch):
    monkeypatch.setenv("OIKOS_API_KEY", "correct-key-123")
    client = TestClient(create_app())
    r = client.get("/api/config", headers={"X-API-Key": "correct-key-123"})
    assert r.status_code == 200


def test_auth_health_exempt(monkeypatch):
    """Health endpoint must be accessible without auth."""
    monkeypatch.setenv("OIKOS_API_KEY", "secret")
    client = TestClient(create_app())
    r = client.get("/api/health")
    assert r.status_code == 200


# ── Settings round-trip ─────────────────────────────────────────────

def test_settings_round_trip(client, tmp_path, monkeypatch):
    import core.interface.settings as mod
    monkeypatch.setattr(mod, "SETTINGS_FILE", tmp_path / "settings.json")
    mod._overrides.clear()
    mod._loaded = True

    r = client.put("/api/settings", json={"key": "inference_model", "value": "test-model:7b"})
    assert r.status_code == 200
    assert r.json()["ok"] is True

    r = client.get("/api/settings")
    assert r.status_code == 200
    assert r.json()["inference_model"] == "test-model:7b"


def test_settings_rejects_immutable(client):
    r = client.put("/api/settings", json={"key": "project_root", "value": "/tmp"})
    assert r.status_code == 400


# ── Upload ──────────────────────────────────────────────────────────

def test_upload_rejects_oversized(client):
    big_content = b"x" * (1024 * 1024 + 1)
    r = client.post("/api/upload", files={"file": ("big.txt", big_content, "text/plain")})
    assert r.status_code == 200
    assert "error" in r.json()
    assert "too large" in r.json()["error"].lower()


# ── Search ──────────────────────────────────────────────────────────

@patch("core.memory.search.hybrid_search")
def test_search_returns_expected_format(mock_search, client):
    mock_result = MagicMock()
    mock_result.content = "result text"
    mock_result.source_path = "vault/knowledge/test.md"
    mock_result.final_score = 0.85
    mock_result.tier.value = "semantic"
    mock_search.return_value = [mock_result]

    r = client.get("/api/search?q=test")
    assert r.status_code == 200
    data = r.json()
    assert data["count"] == 1
    assert data["results"][0]["source_path"] == "vault/knowledge/test.md"
    assert "query" in data


# ── Suggestions SSE ─────────────────────────────────────────────────

def test_suggestions_streams_sse(client):
    chunk1, chunk2 = MagicMock(), MagicMock()
    chunk1.message = MagicMock(content="Suggestion line one\n")
    chunk2.message = MagicMock(content="Suggestion line two")

    mock_client = MagicMock()
    mock_client.chat.return_value = iter([chunk1, chunk2])

    with patch("core.cognition.inference.get_inference_client", return_value=mock_client):
        r = client.get("/api/chat/suggestions?category=Code+Generation")

    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    lines = [l for l in r.text.split("\n") if l.startswith("data: ")]
    assert len(lines) >= 3  # at least 2 deltas + done
    last = json.loads(lines[-1].removeprefix("data: "))
    assert last["done"] is True
    first = json.loads(lines[0].removeprefix("data: "))
    assert "delta" in first


def test_suggestions_requires_category(client):
    r = client.get("/api/chat/suggestions")
    assert r.status_code == 422
