"""Tests for Module 5 — event bus, inference_active, cloud health check, event API."""

from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ── Event Bus ────────────────────────────────────────────────────────

class TestEventBus:
    def test_emit_and_read(self, tmp_path):
        from core.autonomic.events import emit_event, read_events, EVENTS_LOG

        log_path = tmp_path / "events.jsonl"
        with patch("core.autonomic.events.EVENTS_LOG", log_path):
            emit_event("fsm", "transition", {"from": "active", "to": "idle"})
            emit_event("inference", "start", {"route": "local"})
            emit_event("agent", "gauntlet_start", {})

            events = read_events()
            assert len(events) == 3
            assert events[0]["category"] == "fsm"
            assert events[0]["type"] == "transition"
            assert events[1]["category"] == "inference"
            assert events[2]["category"] == "agent"

    def test_read_with_since_filter(self, tmp_path):
        from core.autonomic.events import emit_event, read_events

        log_path = tmp_path / "events.jsonl"
        with patch("core.autonomic.events.EVENTS_LOG", log_path):
            emit_event("fsm", "transition", {"from": "active", "to": "idle"})

            events = read_events()
            assert len(events) == 1
            ts = events[0]["timestamp"]

            time.sleep(0.01)  # ensure distinct timestamp
            emit_event("inference", "start", {"route": "local"})
            events_after = read_events(since=ts)
            assert len(events_after) == 1
            assert events_after[0]["category"] == "inference"

    def test_read_with_limit(self, tmp_path):
        from core.autonomic.events import emit_event, read_events

        log_path = tmp_path / "events.jsonl"
        with patch("core.autonomic.events.EVENTS_LOG", log_path):
            for i in range(10):
                emit_event("test", f"event_{i}", {})

            events = read_events(limit=3)
            assert len(events) == 3
            assert events[-1]["type"] == "event_9"

    def test_read_empty_file(self, tmp_path):
        from core.autonomic.events import read_events

        log_path = tmp_path / "events.jsonl"
        with patch("core.autonomic.events.EVENTS_LOG", log_path):
            events = read_events()
            assert events == []

    def test_emit_creates_parent_dirs(self, tmp_path):
        from core.autonomic.events import emit_event

        log_path = tmp_path / "deep" / "nested" / "events.jsonl"
        with patch("core.autonomic.events.EVENTS_LOG", log_path):
            emit_event("test", "create_dirs", {})
            assert log_path.exists()


# ── Inference Active Context Manager ─────────────────────────────────

class TestInferenceActive:
    def test_context_manager_sets_and_clears_flag(self):
        import core.autonomic.daemon as daemon

        assert daemon._inference_active is False

        with daemon.inference_active():
            assert daemon._inference_active is True

        assert daemon._inference_active is False

    def test_context_manager_clears_on_exception(self):
        import core.autonomic.daemon as daemon

        with pytest.raises(ValueError):
            with daemon.inference_active():
                assert daemon._inference_active is True
                raise ValueError("boom")

        assert daemon._inference_active is False

    def test_vram_yield_skipped_when_inference_active(self):
        import core.autonomic.daemon as daemon

        daemon._inference_active = True
        try:
            daemon._check_vram_pressure()
            # Should return early without touching pynvml
        finally:
            daemon._inference_active = False


# ── Cloud Model Health Check ─────────────────────────────────────────

class TestCloudHealthCheck:
    def setup_method(self):
        import core.cognition.cloud as cloud
        cloud._model_validated = False

    @patch("core.cognition.cloud.get_cloud_client")
    def test_health_check_passes(self, mock_client):
        from core.cognition.cloud import _check_cloud_model

        client = MagicMock()
        mock_client.return_value = client

        _check_cloud_model(client, "gemini-2.5-pro")
        client.models.get.assert_called_once_with(model="gemini-2.5-pro")

    @patch("core.cognition.cloud.get_cloud_client")
    def test_health_check_skipped_after_first_call(self, mock_client):
        from core.cognition.cloud import _check_cloud_model
        import core.cognition.cloud as cloud

        client = MagicMock()
        cloud._model_validated = True

        _check_cloud_model(client, "gemini-2.5-pro")
        client.models.get.assert_not_called()

    @patch("core.autonomic.events.emit_event")
    @patch("core.cognition.cloud.get_cloud_client")
    def test_health_check_emits_event_on_failure(self, mock_client, mock_emit):
        from google.genai.errors import APIError
        from core.cognition.cloud import _check_cloud_model

        client = MagicMock()
        error = APIError("Not Found", response_json={})
        error.code = 404
        client.models.get.side_effect = error

        with pytest.raises(ValueError, match="unavailable"):
            _check_cloud_model(client, "gemini-2.5-pro")

        mock_emit.assert_called_once()
        call_args = mock_emit.call_args
        assert call_args[0][0] == "cloud"
        assert call_args[0][1] == "model_health_check_failed"


# ── Event Emissions in Existing Code ─────────────────────────────────

class TestEventEmissions:
    @patch("core.autonomic.events.emit_event")
    def test_fsm_transition_emits_event(self, mock_emit, tmp_path):
        from core.autonomic.fsm import transition_to, _save_state, get_current_state
        from core.interface.models import SystemState

        state_file = tmp_path / "state.json"
        log_file = tmp_path / "transitions.jsonl"

        with patch("core.autonomic.fsm.FSM_STATE_FILE", state_file), \
             patch("core.autonomic.fsm.FSM_TRANSITION_LOG", log_file):
            _save_state(SystemState.ACTIVE)
            transition_to(SystemState.IDLE, trigger="test")

            # IDLE callbacks trigger consolidation which also emits events
            mock_emit.assert_any_call(
                "fsm", "transition",
                {"from": "active", "to": "idle", "trigger": "test"},
            )


# ── Event API Endpoint ───────────────────────────────────────────────

class TestEventAPI:
    @patch("core.autonomic.events.read_events", return_value=[
        {"timestamp": "2026-03-02T12:00:00", "category": "fsm", "type": "transition", "data": {}},
    ])
    def test_get_events(self, mock_read):
        from fastapi.testclient import TestClient
        from core.interface.api.server import create_app

        client = TestClient(create_app())
        r = client.get("/api/events")
        assert r.status_code == 200
        assert len(r.json()) == 1
        assert r.json()[0]["category"] == "fsm"

    @patch("core.autonomic.events.read_events", return_value=[])
    def test_get_events_with_since(self, mock_read):
        from fastapi.testclient import TestClient
        from core.interface.api.server import create_app

        client = TestClient(create_app())
        r = client.get("/api/events?since=2026-03-02T00:00:00")
        assert r.status_code == 200
        mock_read.assert_called_once_with(since="2026-03-02T00:00:00", limit=50)
