"""Tests for LocalInferenceManager Protocol + OllamaManager.should_run()."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.autonomic.inference_manager import OllamaManager


def _make_config(
    *,
    default: str = "local",
    fallback: str | None = None,
    providers: dict | None = None,
) -> dict:
    """Build a minimal providers.toml-shaped dict."""
    general: dict = {"default": default}
    if fallback:
        general["fallback"] = fallback
    return {
        "general": general,
        "providers": providers or {
            "local": {"type": "ollama", "enabled": True},
        },
    }


def _make_room(allowed_providers: list[str] | None = None) -> MagicMock:
    room = MagicMock()
    room.allowed_providers = allowed_providers
    return room


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_should_run_true_when_ollama_is_default():
    """Global default points to an Ollama provider → should_run() is True."""
    config = _make_config(
        default="local",
        providers={"local": {"type": "ollama", "enabled": True}},
    )
    with patch(
        "core.autonomic.inference_manager.load_providers_config", return_value=config
    ):
        manager = OllamaManager()
        manager.reload_config()
        assert manager.should_run() is True


def test_should_run_false_when_cloud_only():
    """No Ollama provider in config → should_run() is False."""
    config = _make_config(
        default="claude",
        providers={"claude": {"type": "anthropic", "enabled": True}},
    )
    with patch(
        "core.autonomic.inference_manager.load_providers_config", return_value=config
    ):
        with patch(
            "core.autonomic.inference_manager.get_room_manager"
        ) as mock_rm:
            mock_rm.return_value.list_rooms.return_value = []
            manager = OllamaManager()
            manager.reload_config()
            assert manager.should_run() is False


def test_should_run_true_when_room_uses_ollama():
    """Ollama not the global default, but a Room references it → True."""
    config = _make_config(
        default="claude",
        providers={
            "claude": {"type": "anthropic", "enabled": True},
            "local": {"type": "ollama", "enabled": True},
        },
    )
    room = _make_room(allowed_providers=["local"])
    with patch(
        "core.autonomic.inference_manager.load_providers_config", return_value=config
    ):
        with patch(
            "core.autonomic.inference_manager.get_room_manager"
        ) as mock_rm:
            mock_rm.return_value.list_rooms.return_value = [room]
            manager = OllamaManager()
            manager.reload_config()
            assert manager.should_run() is True


def test_should_run_false_when_ollama_disabled():
    """Ollama provider exists but enabled=False → not counted → False."""
    config = _make_config(
        default="local",
        providers={"local": {"type": "ollama", "enabled": False}},
    )
    with patch(
        "core.autonomic.inference_manager.load_providers_config", return_value=config
    ):
        with patch(
            "core.autonomic.inference_manager.get_room_manager"
        ) as mock_rm:
            mock_rm.return_value.list_rooms.return_value = []
            manager = OllamaManager()
            manager.reload_config()
            assert manager.should_run() is False


def test_should_run_false_when_no_providers_toml():
    """Config load raises → safe default is False."""
    with patch(
        "core.autonomic.inference_manager.load_providers_config",
        side_effect=FileNotFoundError("no providers.toml"),
    ):
        manager = OllamaManager()
        manager.reload_config()
        assert manager.should_run() is False


# ---------------------------------------------------------------------------
# health_check
# ---------------------------------------------------------------------------


def test_health_check_success(tmp_path):
    m = OllamaManager(stop_file=tmp_path / "ollama_stopped")
    mock_response = MagicMock()
    mock_response.status_code = 200
    with patch("core.autonomic.inference_manager.httpx") as mock_httpx:
        mock_httpx.get.return_value = mock_response
        result = asyncio.run(m.health_check())
    assert result is True
    mock_httpx.get.assert_called_once_with("http://localhost:11434/api/tags", timeout=3.0)


def test_health_check_timeout(tmp_path):
    m = OllamaManager(stop_file=tmp_path / "ollama_stopped")
    with patch("core.autonomic.inference_manager.httpx") as mock_httpx:
        mock_httpx.get.side_effect = Exception("timeout")
        result = asyncio.run(m.health_check())
    assert result is False


def test_health_check_connection_refused(tmp_path):
    m = OllamaManager(stop_file=tmp_path / "ollama_stopped")
    with patch("core.autonomic.inference_manager.httpx") as mock_httpx:
        mock_httpx.get.side_effect = ConnectionError("refused")
        result = asyncio.run(m.health_check())
    assert result is False


# ---------------------------------------------------------------------------
# stop-file
# ---------------------------------------------------------------------------


def test_stop_file_written_on_stop(tmp_path):
    m = OllamaManager(stop_file=tmp_path / "ollama_stopped")
    with patch("core.autonomic.inference_manager._find_ollama_pid", return_value=1234), \
         patch("core.autonomic.inference_manager._terminate_process"):
        asyncio.run(m.stop())
    assert m._stop_file.exists()


def test_stop_file_deleted_on_start(tmp_path):
    m = OllamaManager(stop_file=tmp_path / "ollama_stopped")
    m._stop_file.write_text("stopped", encoding="utf-8")
    mock_response = MagicMock()
    mock_response.status_code = 200
    with patch("core.autonomic.inference_manager.subprocess"), \
         patch("core.autonomic.inference_manager.httpx") as mock_httpx, \
         patch("core.autonomic.inference_manager.asyncio.sleep", new=AsyncMock()):
        mock_httpx.get.return_value = mock_response
        result = asyncio.run(m.start())
    assert result is True
    assert not m._stop_file.exists()


def test_stop_file_directory_created(tmp_path):
    stop_file = tmp_path / "flags" / "ollama_stopped"
    m = OllamaManager(stop_file=stop_file)
    with patch("core.autonomic.inference_manager._find_ollama_pid", return_value=1234), \
         patch("core.autonomic.inference_manager._terminate_process"):
        asyncio.run(m.stop())
    assert stop_file.parent.exists()
    assert stop_file.exists()


# ---------------------------------------------------------------------------
# start
# ---------------------------------------------------------------------------


def test_start_launches_ollama_serve(tmp_path):
    """Test that start() spawns ollama when it's not already running."""
    m = OllamaManager(stop_file=tmp_path / "ollama_stopped")
    mock_response = MagicMock()
    mock_response.status_code = 200
    with patch("core.autonomic.inference_manager.subprocess") as mock_sub, \
         patch("core.autonomic.inference_manager.httpx") as mock_httpx, \
         patch("core.autonomic.inference_manager.asyncio.sleep", new=AsyncMock()):
        # First health_check returns False (not running), then True (healthy after spawn)
        mock_httpx.get.side_effect = [Exception("Not running"), MagicMock(status_code=200)]
        result = asyncio.run(m.start())
    mock_sub.Popen.assert_called_once()
    args = mock_sub.Popen.call_args[0][0]
    assert args == ["ollama", "serve"]
    assert result is True


def test_start_returns_false_on_health_timeout(tmp_path):
    m = OllamaManager(stop_file=tmp_path / "ollama_stopped")
    with patch("core.autonomic.inference_manager.subprocess"), \
         patch("core.autonomic.inference_manager.httpx") as mock_httpx, \
         patch("core.autonomic.inference_manager.asyncio.sleep", new=AsyncMock()):
        mock_httpx.get.side_effect = ConnectionError("refused")
        result = asyncio.run(m.start())
    assert result is False


# ---------------------------------------------------------------------------
# restart
# ---------------------------------------------------------------------------


def test_restart_success(tmp_path):
    m = OllamaManager(stop_file=tmp_path / "ollama_stopped")
    mock_response = MagicMock()
    mock_response.status_code = 200
    with patch("core.autonomic.inference_manager._find_ollama_pid", return_value=1234), \
         patch("core.autonomic.inference_manager._terminate_process"), \
         patch("core.autonomic.inference_manager.subprocess"), \
         patch("core.autonomic.inference_manager.httpx") as mock_httpx, \
         patch("core.autonomic.inference_manager.asyncio.sleep", new=AsyncMock()):
        mock_httpx.get.return_value = mock_response
        result = asyncio.run(m.restart())
    assert result is True


# ---------------------------------------------------------------------------
# is_intentional_stop
# ---------------------------------------------------------------------------


def test_is_intentional_stop(tmp_path):
    m = OllamaManager(stop_file=tmp_path / "ollama_stopped")
    assert m.is_intentional_stop() is False
    m._stop_file.write_text("stopped", encoding="utf-8")
    assert m.is_intentional_stop() is True


# ---------------------------------------------------------------------------
# Daemon integration tests
# ---------------------------------------------------------------------------

import time


def test_restart_backoff_constants():
    """Restart attempts use 5s, 15s, 45s backoff."""
    from core.autonomic.daemon import RESTART_BACKOFF
    assert RESTART_BACKOFF == [5, 15, 45]


def test_restart_exhaustion_transitions_to_idle():
    """After MAX_RESTART_ATTEMPTS, daemon transitions FSM to IDLE."""
    import core.autonomic.daemon as daemon
    daemon._restart_attempts = 3
    daemon._restart_window_start = time.time()

    mock_manager = MagicMock()
    mock_manager.backend_name.return_value = "Ollama"

    with patch("core.autonomic.daemon._inference_manager", mock_manager), \
         patch("core.autonomic.fsm.transition_to") as mock_transition, \
         patch("core.autonomic.events.emit_event"):
        daemon._attempt_restart()

    from core.interface.models import SystemState
    mock_transition.assert_called_once()
    assert mock_transition.call_args[0][0] == SystemState.IDLE


def test_restart_window_resets_after_30_min():
    """Restart counter resets when window expires."""
    import core.autonomic.daemon as daemon
    daemon._restart_attempts = 2
    daemon._restart_window_start = time.time() - 1900  # >30 min ago

    mock_manager = MagicMock()
    mock_manager.backend_name.return_value = "Ollama"
    mock_manager.restart = AsyncMock(return_value=True)

    with patch("core.autonomic.daemon._inference_manager", mock_manager), \
         patch("core.autonomic.daemon.time") as mock_time:
        mock_time.time.return_value = time.time()
        mock_time.sleep = MagicMock()
        daemon._attempt_restart()

    # Window reset + successful restart → attempts back to 0
    assert daemon._restart_attempts == 0


def test_stop_file_blocks_restart():
    """Daemon skips health check when stop-file indicates intentional stop."""
    import core.autonomic.daemon as daemon

    mock_manager = MagicMock()
    mock_manager.should_run.return_value = True
    mock_manager.is_intentional_stop.return_value = True

    with patch("core.autonomic.daemon._inference_manager", mock_manager):
        daemon._check_local_inference()

    mock_manager.health_check.assert_not_called()


def test_daemon_skips_inference_when_no_manager():
    """Daemon with _inference_manager=None skips all local inference logic."""
    import core.autonomic.daemon as daemon

    with patch("core.autonomic.daemon._inference_manager", None):
        daemon._check_local_inference()  # Should not raise


def test_no_transition_to_asleep_on_exhaustion():
    """FSM transitions to IDLE, never ASLEEP, on restart exhaustion."""
    import core.autonomic.daemon as daemon
    daemon._restart_attempts = 3
    daemon._restart_window_start = time.time()

    mock_manager = MagicMock()
    mock_manager.backend_name.return_value = "Ollama"

    with patch("core.autonomic.daemon._inference_manager", mock_manager), \
         patch("core.autonomic.fsm.transition_to") as mock_transition, \
         patch("core.autonomic.events.emit_event"):
        daemon._attempt_restart()

    from core.interface.models import SystemState
    if mock_transition.called:
        assert mock_transition.call_args[0][0] != SystemState.ASLEEP


# ---------------------------------------------------------------------------
# Config mtime watcher
# ---------------------------------------------------------------------------


def test_config_reload_on_mtime_change(tmp_path):
    """Manager detects config file mtime change."""
    toml_file = tmp_path / "providers.toml"
    toml_file.write_text(
        '[general]\ndefault = "local"\n\n[providers.local]\ntype = "ollama"\nenabled = true\n'
    )

    m = OllamaManager(stop_file=tmp_path / "ollama_stopped")

    config_ollama = {
        "general": {"default": "local"},
        "providers": {"local": {"type": "ollama", "enabled": True}},
    }
    config_cloud = {
        "general": {"default": "gemini"},
        "providers": {"gemini": {"type": "gemini", "enabled": True}},
    }

    with patch("core.autonomic.inference_manager.load_providers_config", return_value=config_ollama), \
         patch("core.autonomic.inference_manager.PROVIDERS_TOML_PATH", toml_file):
        m.reload_config()
        assert m.should_run() is True
        assert m.check_config_changed(toml_file) is False  # Just loaded

    # Simulate file change
    import time as t
    t.sleep(0.05)
    toml_file.write_text('[general]\ndefault = "gemini"\n')

    with patch("core.autonomic.inference_manager.PROVIDERS_TOML_PATH", toml_file):
        assert m.check_config_changed(toml_file) is True

    with patch("core.autonomic.inference_manager.load_providers_config", return_value=config_cloud), \
         patch("core.autonomic.inference_manager.PROVIDERS_TOML_PATH", toml_file), \
         patch("core.autonomic.inference_manager.get_room_manager") as mock_rm:
        mock_rm.return_value.list_rooms.return_value = []
        m.reload_config()
        assert m.should_run() is False
