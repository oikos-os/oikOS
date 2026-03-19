"""Tests for FSM — state persistence, transitions, callbacks, auto-commit."""

import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from core.autonomic.fsm import (
    VALID_TRANSITIONS,
    _auto_commit_vault,
    _log_transition,
    _on_enter_active,
    _on_enter_asleep,
    _on_enter_idle,
    _save_state,
    get_current_state,
    get_last_transition_time,
    transition_to,
)
from core.interface.models import SystemState


@pytest.fixture
def fsm_state_file(tmp_path, monkeypatch):
    """Redirect FSM state file to tmp_path."""
    state_file = tmp_path / ".system_state.json"
    monkeypatch.setattr("core.autonomic.fsm.FSM_STATE_FILE", state_file)
    return state_file


@pytest.fixture
def fsm_log_file(tmp_path, monkeypatch):
    """Redirect FSM transition log to tmp_path."""
    log_file = tmp_path / "state_transitions.jsonl"
    monkeypatch.setattr("core.autonomic.fsm.FSM_TRANSITION_LOG", log_file)
    return log_file


def test_default_state_is_active(fsm_state_file):
    """No state file → ACTIVE."""
    assert get_current_state() == SystemState.ACTIVE


def test_save_load_round_trip(fsm_state_file):
    """Persist and reload state."""
    _save_state(SystemState.IDLE)
    assert get_current_state() == SystemState.IDLE

    _save_state(SystemState.ASLEEP)
    assert get_current_state() == SystemState.ASLEEP


def test_corrupt_state_file_defaults_active(fsm_state_file):
    """Corrupt JSON → graceful fallback to ACTIVE."""
    fsm_state_file.write_text("{bad json!!", encoding="utf-8")
    assert get_current_state() == SystemState.ACTIVE


def test_transition_active_to_idle(fsm_state_file, fsm_log_file):
    """ACTIVE → IDLE fires callback."""
    _save_state(SystemState.ACTIVE)

    with patch("core.autonomic.fsm._on_enter_idle", return_value={"reindex": {}, "git": {}}) as mock_cb:
        result = transition_to(SystemState.IDLE, trigger="test")
        mock_cb.assert_called_once()

    assert result["transition"] == "active -> idle"


def test_transition_idle_to_active(fsm_state_file, fsm_log_file):
    """IDLE → ACTIVE fires on_enter_active."""
    _save_state(SystemState.IDLE)

    with patch("core.autonomic.fsm._on_enter_active", return_value={"briefing_ready": True}) as mock_cb:
        result = transition_to(SystemState.ACTIVE, trigger="test")
        mock_cb.assert_called_once()

    assert result["transition"] == "idle -> active"
    assert result["briefing_ready"] is True


def test_same_state_is_noop(fsm_state_file, fsm_log_file):
    """Same-state transition → no callbacks, no log."""
    _save_state(SystemState.ACTIVE)
    result = transition_to(SystemState.ACTIVE, trigger="test")
    assert result["transition"] is None
    assert not fsm_log_file.exists()


def test_invalid_transition_raises(fsm_state_file, fsm_log_file):
    """ASLEEP → IDLE is invalid."""
    _save_state(SystemState.ASLEEP)
    with pytest.raises(ValueError, match="Invalid transition"):
        transition_to(SystemState.IDLE, trigger="test")


def test_transition_log_written(fsm_state_file, fsm_log_file):
    """Transition appends JSONL record."""
    _save_state(SystemState.ACTIVE)

    with patch("core.autonomic.fsm._on_enter_idle", return_value={}):
        transition_to(SystemState.IDLE, trigger="test_trigger")

    lines = fsm_log_file.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["from"] == "active"
    assert record["to"] == "idle"
    assert record["trigger"] == "test_trigger"


def test_auto_commit_no_changes(tmp_path, monkeypatch):
    """No vault changes → no commit."""
    monkeypatch.setattr("core.autonomic.fsm.VAULT_DIR", tmp_path / "vault")
    with patch("core.autonomic.fsm.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="")
        result = _auto_commit_vault()
    assert result["committed"] is False


def test_auto_commit_with_changes(tmp_path, monkeypatch):
    """Vault changes → git add + commit."""
    monkeypatch.setattr("core.autonomic.fsm.VAULT_DIR", tmp_path / "vault")

    status_result = MagicMock(returncode=0, stdout=" M vault/identity/TELOS.md\n")
    commit_result = MagicMock(returncode=0, stdout="")

    with patch("core.autonomic.fsm.subprocess.run") as mock_run:
        mock_run.side_effect = [status_result, MagicMock(returncode=0), commit_result]
        result = _auto_commit_vault()

    assert result["committed"] is True
    assert "vault/identity/TELOS.md" in result["files"]


def test_handler_auto_transition_from_idle(fsm_state_file, fsm_log_file):
    """Handler step 0b auto-transitions from IDLE to ACTIVE on query."""
    _save_state(SystemState.IDLE)

    with patch("core.autonomic.fsm._on_enter_active", return_value={"briefing_ready": True}):
        # Simulate what handler does
        from core.autonomic.fsm import get_current_state, transition_to

        if get_current_state() in (SystemState.IDLE, SystemState.ASLEEP):
            result = transition_to(SystemState.ACTIVE, trigger="auto:query")

    assert get_current_state() == SystemState.ACTIVE


def test_on_enter_active_returns_briefing_ready():
    """on_enter_active signals briefing is ready."""
    result = _on_enter_active()
    assert result["briefing_ready"] is True


def test_on_enter_asleep_returns_flushed():
    """on_enter_asleep signals flush complete."""
    result = _on_enter_asleep()
    assert result["flushed"] is True


def test_get_last_transition_time(fsm_state_file):
    """Last transition timestamp returned after save."""
    assert get_last_transition_time() is None

    _save_state(SystemState.IDLE)
    ts = get_last_transition_time()
    assert ts is not None
    # Should be parseable ISO format
    datetime.fromisoformat(ts)
