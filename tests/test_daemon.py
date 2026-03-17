"""Tests for core.autonomic.daemon — heartbeat loop, VRAM, health, service lifecycle."""

from __future__ import annotations

import json
import os
from unittest.mock import MagicMock, patch

import pytest

import core.autonomic.daemon as daemon
from core.interface.models import SystemState


@pytest.fixture(autouse=True)
def _reset_daemon_state():
    """Reset module-level state between tests."""
    daemon._running = False
    daemon._vram_yielded = False
    daemon._health_failures = 0
    daemon._last_health_check = 0.0
    daemon._inference_active = False
    daemon._start_time = 0.0
    daemon._last_vault_mtime = 0.0
    daemon._last_session_check = 0.0
    daemon._last_budget_check = 0.0
    daemon._budget_alert_fired = False
    daemon._budget_critical_fired = False
    daemon._last_log_rotation = 0.0
    daemon._last_prewarm_check = 0.0
    daemon._today_activity_logged = False
    yield


# ── Test 1: Idle timeout triggers IDLE transition ─────────────────────
def test_idle_timeout_triggers_transition():
    mock_transition = MagicMock()
    with patch("core.autonomic.daemon._get_idle_seconds", return_value=901.0), \
         patch("core.autonomic.fsm.get_current_state", return_value=SystemState.ACTIVE), \
         patch("core.autonomic.fsm.transition_to", mock_transition):
        daemon._check_input_activity()
    mock_transition.assert_called_once_with(SystemState.IDLE, trigger="daemon:inactivity")


# ── Test 2: Activity resume triggers ACTIVE transition ────────────────
def test_activity_resume_triggers_active():
    mock_transition = MagicMock()
    with patch("core.autonomic.daemon._get_idle_seconds", return_value=60.0), \
         patch("core.autonomic.fsm.get_current_state", return_value=SystemState.IDLE), \
         patch("core.autonomic.fsm.transition_to", mock_transition):
        daemon._check_input_activity()
    mock_transition.assert_called_once_with(SystemState.ACTIVE, trigger="daemon:activity")


# ── Test 3: VRAM yield unloads model ─────────────────────────────────
@patch("core.autonomic.daemon.subprocess")
def test_vram_yield_unloads_model(mock_subprocess):
    mock_pynvml = MagicMock()
    mock_info = MagicMock()
    mock_info.used = 11500 * 1024 * 1024  # 11500 MB > 11264 threshold
    mock_pynvml.nvmlDeviceGetMemoryInfo.return_value = mock_info

    with patch.dict("sys.modules", {"pynvml": mock_pynvml}):
        daemon._vram_yielded = False
        daemon._inference_active = False
        daemon._check_vram_pressure()

    mock_subprocess.run.assert_called_once()
    args = mock_subprocess.run.call_args
    assert "ollama" in args[0][0]
    assert "stop" in args[0][0]
    assert daemon._vram_yielded is True


# ── Test 4: VRAM reload on pressure drop ──────────────────────────────
def test_vram_reload_on_pressure_drop():
    mock_pynvml = MagicMock()
    mock_info = MagicMock()
    mock_info.used = 5000 * 1024 * 1024  # 5000 MB < 11264 * 0.8
    mock_pynvml.nvmlDeviceGetMemoryInfo.return_value = mock_info

    mock_ollama = MagicMock()

    with patch.dict("sys.modules", {"pynvml": mock_pynvml, "ollama": mock_ollama}):
        daemon._vram_yielded = True
        daemon._inference_active = False
        daemon._check_vram_pressure()

    mock_ollama.Client().generate.assert_called_once()
    assert daemon._vram_yielded is False


# ── Test 5: No yield during inference ─────────────────────────────────
@patch("core.autonomic.daemon.subprocess")
def test_vram_no_yield_during_inference(mock_subprocess):
    daemon._inference_active = True
    daemon._vram_yielded = False
    daemon._check_vram_pressure()
    mock_subprocess.run.assert_not_called()
    assert daemon._vram_yielded is False


# ── Test 6: Health check success resets failures ──────────────────────
def test_health_check_success_resets_failures():
    mock_ollama = MagicMock()
    daemon._health_failures = 2
    daemon._last_health_check = 0.0

    with patch.dict("sys.modules", {"ollama": mock_ollama}), \
         patch("time.monotonic", return_value=100.0):
        daemon._check_ollama_health()

    assert daemon._health_failures == 0


# ── Test 7: Health check failure restarts after 3 ─────────────────────
@patch("core.autonomic.daemon.subprocess")
def test_health_check_failure_restarts_after_3(mock_subprocess):
    mock_ollama = MagicMock()
    mock_ollama.Client().list.side_effect = Exception("connection refused")
    daemon._health_failures = 2
    daemon._last_health_check = 0.0

    with patch.dict("sys.modules", {"ollama": mock_ollama}), \
         patch("time.monotonic", return_value=100.0):
        daemon._check_ollama_health()

    mock_subprocess.Popen.assert_called_once()
    args = mock_subprocess.Popen.call_args
    assert args[0][0] == ["ollama", "serve"]
    assert daemon._health_failures == 0


# ── Test 8: install_service calls schtasks ────────────────────────────
@patch("core.autonomic.daemon.subprocess.run")
def test_install_service_calls_schtasks(mock_run):
    daemon.install_service()
    mock_run.assert_called_once()
    args = mock_run.call_args[0][0]
    assert args[0] == "schtasks"
    assert "/create" in args
    assert "OIKOS_DAEMON" in args
    assert "/sc" in args
    assert "onlogon" in args


# ── Test 9: uninstall_service calls schtasks ──────────────────────────
@patch("core.autonomic.daemon.subprocess.run")
def test_uninstall_service_calls_schtasks(mock_run):
    daemon.uninstall_service()
    mock_run.assert_called_once()
    args = mock_run.call_args[0][0]
    assert args[0] == "schtasks"
    assert "/delete" in args
    assert "OIKOS_DAEMON" in args


# ── Test 10: heartbeat_tick batches all checks ────────────────────────
@patch("core.autonomic.daemon._check_log_rotation")
@patch("core.autonomic.daemon._check_prewarm")
@patch("core.autonomic.daemon._check_budget_alerts")
@patch("core.autonomic.daemon._check_stale_sessions")
@patch("core.autonomic.daemon._check_vault_changes")
@patch("core.autonomic.daemon._check_ollama_health")
@patch("core.autonomic.daemon._check_vram_pressure")
@patch("core.autonomic.daemon._check_input_activity")
def test_heartbeat_tick_batches_all_checks(mock_input, mock_vram, mock_health,
                                           mock_vault, mock_session, mock_budget,
                                           mock_prewarm, mock_rotation):
    daemon.heartbeat_tick()
    mock_input.assert_called_once()
    mock_vram.assert_called_once()
    mock_health.assert_called_once()
    mock_vault.assert_called_once()
    mock_session.assert_called_once()
    mock_budget.assert_called_once()
    mock_prewarm.assert_called_once()
    mock_rotation.assert_called_once()


# ── Test 11: ASLEEP state skips idle transition ───────────────────────
def test_asleep_state_skips_idle_transition():
    mock_transition = MagicMock()
    with patch("core.autonomic.daemon._get_idle_seconds", return_value=901.0), \
         patch("core.autonomic.fsm.get_current_state", return_value=SystemState.ASLEEP), \
         patch("core.autonomic.fsm.transition_to", mock_transition):
        daemon._check_input_activity()
    mock_transition.assert_not_called()


# ── Test 12: PID file lifecycle ───────────────────────────────────────
def test_pid_file_lifecycle(tmp_path):
    pid_file = tmp_path / "daemon.pid"

    with patch("core.autonomic.daemon.DAEMON_PID_FILE", pid_file):
        assert daemon.is_running() is False

        pid_file.write_text(str(os.getpid()), encoding="utf-8")
        assert daemon.is_running() is True

        daemon.stop()
        assert pid_file.exists() is False
        assert daemon.is_running() is False


# ── Test 13: is_running handles stale PID ─────────────────────────────
def test_is_running_stale_pid(tmp_path):
    pid_file = tmp_path / "daemon.pid"
    pid_file.write_text("999999999", encoding="utf-8")

    with patch("core.autonomic.daemon.DAEMON_PID_FILE", pid_file):
        assert daemon.is_running() is False
        assert pid_file.exists() is False


# ══════════════════════════════════════════════════════════════════════
# Feature 1: Vault File Watcher
# ══════════════════════════════════════════════════════════════════════

def test_vault_watcher_detects_new_file(tmp_path):
    watch_dir = tmp_path / "knowledge"
    watch_dir.mkdir()
    (watch_dir / "old.md").write_text("old", encoding="utf-8")

    with patch("core.autonomic.daemon.DAEMON_VAULT_WATCH_DIRS", [watch_dir]):
        # First call: baseline mtime
        daemon._check_vault_changes()
        assert daemon._last_vault_mtime > 0

        # Touch a new file with newer mtime
        import time
        time.sleep(0.05)
        (watch_dir / "new.md").write_text("new", encoding="utf-8")

        mock_index = MagicMock(return_value={"added": 1, "skipped": 0, "deleted": 0})
        with patch("core.memory.indexer.index_vault", mock_index), \
             patch("core.autonomic.events.emit_event"):
            daemon._check_vault_changes()

        mock_index.assert_called_once_with(full_rebuild=False)


def test_vault_watcher_ignores_non_md(tmp_path):
    watch_dir = tmp_path / "knowledge"
    watch_dir.mkdir()
    (watch_dir / "data.txt").write_text("text", encoding="utf-8")

    with patch("core.autonomic.daemon.DAEMON_VAULT_WATCH_DIRS", [watch_dir]):
        daemon._check_vault_changes()
        # No .md files found, so _last_vault_mtime stays 0 (initial baseline)
        assert daemon._last_vault_mtime == 0.0


# ══════════════════════════════════════════════════════════════════════
# Feature 2: Session Auto-Close
# ══════════════════════════════════════════════════════════════════════

def test_session_auto_close_stale(tmp_path):
    from datetime import datetime, timezone, timedelta

    stale_time = (datetime.now(timezone.utc) - timedelta(minutes=60)).isoformat()
    mock_state = {"last_active_at": stale_time, "session_id": "test-123"}
    mock_result = {"session_id": "test-123", "interaction_count": 5}

    with patch("core.memory.session._load_state", return_value=mock_state), \
         patch("core.memory.session.close_session", return_value=mock_result) as mock_close, \
         patch("core.autonomic.events.emit_event") as mock_emit:
        daemon._check_stale_sessions()

    mock_close.assert_called_once()
    mock_emit.assert_called_once()
    assert mock_emit.call_args[0][1] == "session_auto_close"


def test_session_auto_close_leaves_active():
    from datetime import datetime, timezone, timedelta

    recent_time = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    mock_state = {"last_active_at": recent_time, "session_id": "active-456"}

    with patch("core.memory.session._load_state", return_value=mock_state), \
         patch("core.memory.session.close_session") as mock_close:
        daemon._check_stale_sessions()

    mock_close.assert_not_called()


# ══════════════════════════════════════════════════════════════════════
# Feature 3: Budget Alerts
# ══════════════════════════════════════════════════════════════════════

def test_budget_alert_at_80_percent():
    mock_balance = MagicMock()
    mock_balance.monthly_cap = 1000
    mock_balance.used = 850
    mock_balance.remaining = 150

    with patch("core.safety.credits.load_credits", return_value=mock_balance), \
         patch("core.autonomic.events.emit_event") as mock_emit:
        daemon._check_budget_alerts()

    mock_emit.assert_called_once()
    assert mock_emit.call_args[0][1] == "budget_warning"
    assert daemon._budget_alert_fired is True


def test_budget_critical_at_95_percent():
    mock_balance = MagicMock()
    mock_balance.monthly_cap = 1000
    mock_balance.used = 960
    mock_balance.remaining = 40

    with patch("core.safety.credits.load_credits", return_value=mock_balance), \
         patch("core.autonomic.events.emit_event") as mock_emit:
        daemon._check_budget_alerts()

    mock_emit.assert_called_once()
    assert mock_emit.call_args[0][1] == "budget_critical"
    assert daemon._budget_critical_fired is True


# ══════════════════════════════════════════════════════════════════════
# Feature 4: Predictive Prewarm
# ══════════════════════════════════════════════════════════════════════

def test_prewarm_triggers_in_window(tmp_path):
    from datetime import datetime, timezone

    data_file = tmp_path / "activity_schedule.json"
    now = datetime.now(timezone.utc)
    # Create 7 samples all at current hour/minute so prewarm window matches
    samples = [
        {"date": f"2026-02-{20+i}", "first_active_utc": now.isoformat(),
         "hour": now.hour, "minute": now.minute}
        for i in range(7)
    ]
    data_file.write_text(json.dumps({"samples": samples}), encoding="utf-8")

    with patch("core.autonomic.daemon.DAEMON_PREWARM_DATA_FILE", data_file), \
         patch("core.autonomic.daemon._warmup_model") as mock_warmup, \
         patch("core.autonomic.events.emit_event"):
        daemon._check_prewarm()

    mock_warmup.assert_called_once()


# ══════════════════════════════════════════════════════════════════════
# Feature 5: Log Rotation
# ══════════════════════════════════════════════════════════════════════

def test_log_rotation_trims_large_file(tmp_path):
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()

    big_file = logs_dir / "events.jsonl"
    # 3000 lines x ~2KB each = ~6MB (exceeds 5MB threshold)
    line = '{"event": "x' + "a" * 2000 + '"}\n'
    big_file.write_text(line * 3000, encoding="utf-8")

    with patch("core.autonomic.daemon.PROJECT_ROOT", tmp_path), \
         patch("core.autonomic.daemon._last_log_rotation", 0), \
         patch("core.autonomic.daemon.DAEMON_LOG_ROTATION_INTERVAL_SEC", 0), \
         patch("core.autonomic.events.emit_event"):
        daemon._check_log_rotation()

    result_lines = big_file.read_text(encoding="utf-8").strip().split("\n")
    assert len(result_lines) <= 2000


def test_log_rotation_skips_small_file(tmp_path):
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()

    small_file = logs_dir / "small.jsonl"
    small_file.write_text('{"event": 1}\n', encoding="utf-8")

    with patch("core.autonomic.daemon.PROJECT_ROOT", tmp_path):
        daemon._check_log_rotation()

    assert small_file.read_text(encoding="utf-8") == '{"event": 1}\n'


# ══════════════════════════════════════════════════════════════════════
# Feature 6: Activity Logging
# ══════════════════════════════════════════════════════════════════════

def test_activity_logging_writes_schedule(tmp_path):
    data_file = tmp_path / "activity_schedule.json"

    with patch("core.autonomic.daemon.DAEMON_PREWARM_DATA_FILE", data_file):
        daemon._record_daily_activity()

    assert data_file.exists()
    data = json.loads(data_file.read_text(encoding="utf-8"))
    assert len(data["samples"]) == 1
    assert "hour" in data["samples"][0]
    assert "minute" in data["samples"][0]
