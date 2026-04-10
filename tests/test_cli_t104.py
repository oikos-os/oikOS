"""Tests for T-104: CLI completion — snapshot, tui, ask, vault, health, agents, tools, history, config."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from core.interface.cli import main


@pytest.fixture()
def runner():
    return CliRunner()


@pytest.fixture()
def isolated_rooms(tmp_path, monkeypatch):
    """Create a home room with all 8 toolsets."""
    rooms_dir = tmp_path / "rooms"
    rooms_dir.mkdir()
    home = {
        "id": "home",
        "name": "Home",
        "toolsets": ["vault", "system", "file", "browser", "research", "git", "oracle", "google"],
    }
    (rooms_dir / "home.json").write_text(json.dumps(home))
    (tmp_path / "active_room").write_text("home")
    monkeypatch.setattr("core.rooms.manager.ROOMS_DIR", rooms_dir)
    yield
    from core.rooms.manager import reset_room_manager

    reset_room_manager()


def test_bare_oikos_snapshot_enriched(runner, monkeypatch):
    """Mock API returning full state — output contains key fields + uptime."""
    api_response = MagicMock()
    api_response.status_code = 200
    api_response.json.return_value = {"fsm_state": "ACTIVE", "uptime": 7260.0}
    api_response.raise_for_status = MagicMock()

    with patch("core.interface.snapshot.httpx.get", return_value=api_response):
        result = runner.invoke(main, [])

    out = result.output.lower()
    assert "oikos" in out
    assert "home" in out
    assert "active" in out
    assert "2h" in out


def test_bare_oikos_snapshot_api_offline(runner, monkeypatch):
    """API unreachable — disk fields shown, offline/serve hint present."""
    monkeypatch.setattr("core.interface.snapshot.API_TIMEOUT", 0.01)

    with patch("core.interface.snapshot.httpx.get", side_effect=Exception("connect refused")):
        result = runner.invoke(main, [])

    out = result.output.lower()
    assert "oikos" in out
    assert "offline" in out or "serve" in out


def test_oikos_tui_launches(runner, monkeypatch):
    """oikos tui calls boot splash + app.run."""
    mock_splash = MagicMock()
    mock_app_instance = MagicMock()
    mock_app_class = MagicMock(return_value=mock_app_instance)

    monkeypatch.setattr("core.interface.tui.app.run_tui_boot_splash", mock_splash)
    monkeypatch.setattr("core.interface.tui.app.OikOSApp", mock_app_class)

    result = runner.invoke(main, ["tui"])

    assert result.exit_code == 0
    mock_splash.assert_called_once()
    mock_app_instance.run.assert_called_once()


def test_oikos_help_unchanged(runner):
    """oikos --help still shows core commands."""
    result = runner.invoke(main, ["--help"])
    out = result.output.lower()
    assert "search" in out
    assert "query" in out
    assert "serve" in out


# ── Task 3: ask alias + vault ───────────────────────────────────────


def test_ask_alias(runner):
    """oikos ask is recognized as a command (delegates to query)."""
    result = runner.invoke(main, ["ask", "hello world", "--no-stream"], catch_exceptions=False)
    # It will fail on inference, but it should NOT be "No such command"
    assert "No such command" not in result.output


def test_vault_bare_lists_dirs(runner, tmp_path, monkeypatch):
    """Bare 'oikos vault' lists vault subdirectories with .md counts."""
    vault_dir = tmp_path / "vault"
    vault_dir.mkdir()
    (vault_dir / "identity").mkdir()
    (vault_dir / "identity" / "core.md").touch()
    (vault_dir / "identity" / "values.md").touch()
    (vault_dir / "knowledge").mkdir()
    (vault_dir / "knowledge" / "notes.md").touch()

    monkeypatch.setattr("core.interface.config.PROJECT_ROOT", tmp_path)

    result = runner.invoke(main, ["vault"])
    out = result.output
    assert "identity" in out
    assert "knowledge" in out


def test_vault_query_delegates_search(runner):
    """oikos vault <query> is recognized and delegates to search."""
    result = runner.invoke(main, ["vault", "test query"])
    # Should not be "No such command"
    assert "No such command" not in result.output


# ── Task 4: health ──────────────────────────────────────────────────


def test_health_all_passing(runner, monkeypatch):
    """All health checks green shows ✓ for each."""
    monkeypatch.setattr("core.interface.cli._check_daemon", lambda: True)
    monkeypatch.setattr("core.interface.cli._check_api", lambda: True)
    monkeypatch.setattr("core.interface.cli._check_ollama", lambda: True)
    monkeypatch.setattr("core.interface.cli._check_vault_index", lambda: True)

    result = runner.invoke(main, ["health"])
    assert result.exit_code == 0
    assert "✓" in result.output


def test_health_partial_failure(runner, monkeypatch):
    """Ollama down shows ✗ while others show ✓."""
    monkeypatch.setattr("core.interface.cli._check_daemon", lambda: True)
    monkeypatch.setattr("core.interface.cli._check_api", lambda: True)
    monkeypatch.setattr("core.interface.cli._check_ollama", lambda: False)
    monkeypatch.setattr("core.interface.cli._check_vault_index", lambda: True)

    result = runner.invoke(main, ["health"])
    assert result.exit_code == 0
    assert "✗" in result.output


# ── Task 5: agents, tools, history ──────────────────────────────────


def test_agents_shows_daemon(runner, monkeypatch):
    """Agents command shows daemon status."""
    monkeypatch.setattr("core.interface.cli._check_daemon", lambda: True)

    result = runner.invoke(main, ["agents"])
    assert result.exit_code == 0
    assert "Daemon" in result.output or "daemon" in result.output.lower()
    assert "active" in result.output.lower()


def test_tools_scoped_to_room(runner, isolated_rooms):
    """Tools command shows toolsets for the active room."""
    result = runner.invoke(main, ["tools"])
    assert result.exit_code == 0
    assert "vault" in result.output.lower()


def test_history_lists_sessions(runner, tmp_path, monkeypatch):
    """History command lists session directories."""
    import core.interface.cli as cli_mod

    (tmp_path / "2026-04-01").mkdir()
    (tmp_path / "2026-04-02").mkdir()
    (tmp_path / "2026-04-03").mkdir()

    monkeypatch.setattr(cli_mod, "SESSIONS_DIR", tmp_path)

    result = runner.invoke(main, ["history"])
    assert result.exit_code == 0
    assert "2026-04-03" in result.output
    assert "2026-04-01" in result.output


# ── Task 6: config ──────────────────────────────────────────────────


def test_config_bare_shows_settings(runner, monkeypatch):
    """Bare 'oikos config' shows tiered settings display including theme."""
    from core.interface.settings_registry import SETTINGS_REGISTRY

    def fake_tiered():
        return {
            "essential": {"theme": {"value": "amber", "description": "Color theme"}},
            "advanced": {},
            "expert": {},
        }

    monkeypatch.setattr("core.interface.settings.get_tiered_settings", fake_tiered)

    result = runner.invoke(main, ["config"])
    assert result.exit_code == 0
    assert "theme" in result.output


def test_config_write_valid_key(runner, tmp_path, monkeypatch):
    """Writing a valid config key persists the value."""
    settings_file = tmp_path / "settings.json"
    settings_file.write_text("{}")

    import core.interface.settings as settings_mod

    monkeypatch.setattr(settings_mod, "SETTINGS_FILE", settings_file)
    monkeypatch.setattr(settings_mod, "_overrides", {})
    monkeypatch.setattr(settings_mod, "_loaded", True)

    result = runner.invoke(main, ["config", "theme", "green"])
    assert result.exit_code == 0
    assert "green" in result.output


def test_config_write_redirect(runner):
    """Writing a redirected key shows the redirect hint."""
    result = runner.invoke(main, ["config", "default_provider", "gemini"])
    assert "oikos provider" in result.output


def test_config_write_unknown_key(runner):
    """Writing an unknown key exits with code 1."""
    result = runner.invoke(main, ["config", "foo", "bar"])
    assert result.exit_code == 1
    assert "unknown" in result.output.lower() or "read-only" in result.output.lower()


def test_config_write_invalid_value(runner):
    """Writing an invalid value type exits with code 1."""
    result = runner.invoke(main, ["config", "api_port", "notanumber"])
    assert result.exit_code == 1
    # Error message comes from registry error_hint or validation message
    assert any(word in result.output.lower() for word in ("invalid", "expected", "must be", "integer"))


# ── Task 8: SmartGroup — room and provider shorthand ───────────────────


def test_bare_room_shows_active(runner, isolated_rooms):
    """oikos room (bare) shows active room and available rooms."""
    result = runner.invoke(main, ["room"])
    assert result.exit_code == 0
    assert "home" in result.output.lower()


def test_room_shorthand_switch(runner, isolated_rooms):
    """oikos room <name> switches to that room."""
    from core.rooms.manager import get_room_manager
    from core.rooms.models import RoomConfig

    mgr = get_room_manager()
    mgr.create_room(RoomConfig(id="work", name="Work", description="Work room"))
    result = runner.invoke(main, ["room", "work"])
    assert result.exit_code == 0
    assert "work" in result.output.lower()
    assert mgr.get_active_room().id == "work"


def test_room_nonexistent_friendly_error(runner, isolated_rooms):
    """oikos room <nonexistent> shows friendly error."""
    result = runner.invoke(main, ["room", "xyz"])
    assert result.exit_code == 1
    assert "xyz" in result.output
    assert "Traceback" not in result.output


def test_bare_provider_shows_active(runner, monkeypatch):
    """oikos provider (bare) shows active provider."""
    from unittest.mock import MagicMock

    mock_reg = MagicMock()
    mock_reg.get_default_name.return_value = "gemini"
    mock_reg.list_all.return_value = ["local", "gemini"]
    mock_provider = MagicMock()
    mock_provider.is_available.return_value = True
    mock_reg.get.return_value = mock_provider
    monkeypatch.setattr(
        "core.cognition.pipeline.dispatch.get_provider_registry", lambda: mock_reg
    )
    result = runner.invoke(main, ["provider"])
    assert result.exit_code == 0
    assert "gemini" in result.output.lower()


def test_provider_shorthand_switch(runner, tmp_path, monkeypatch):
    """oikos provider <name> switches default."""
    import tomllib

    toml_path = tmp_path / "providers.toml"
    toml_path.write_text(
        '[general]\ndefault = "local"\n\n'
        "[providers.local]\n"
        'type = "ollama"\n'
        "enabled = true\n\n"
        "[providers.gemini]\n"
        'type = "gemini"\n'
        "enabled = true\n",
        encoding="utf-8",
    )

    import core.interface.cli as cli_mod

    monkeypatch.setattr(cli_mod, "PROVIDERS_TOML", toml_path)
    # Also patch the lazy resolver so it returns our path
    monkeypatch.setattr(cli_mod, "_get_providers_toml", lambda: toml_path)

    mock_reg = MagicMock()
    mock_reg.list_all.return_value = ["local", "gemini"]
    monkeypatch.setattr(
        "core.cognition.pipeline.dispatch.get_provider_registry", lambda: mock_reg
    )
    result = runner.invoke(main, ["provider", "gemini"])
    assert result.exit_code == 0
    assert "gemini" in result.output.lower()
    with open(toml_path, "rb") as f:
        data = tomllib.load(f)
    assert data["general"]["default"] == "gemini"


def test_provider_nonexistent_friendly_error(runner, monkeypatch):
    """oikos provider <nonexistent> shows friendly error."""
    from unittest.mock import MagicMock

    mock_reg = MagicMock()
    mock_reg.list_all.return_value = ["local", "gemini"]
    monkeypatch.setattr(
        "core.cognition.pipeline.dispatch.get_provider_registry", lambda: mock_reg
    )
    result = runner.invoke(main, ["provider", "xyz"])
    assert result.exit_code == 1
    assert "xyz" in result.output
    assert "Traceback" not in result.output


# ── T-117: config registry integration ──────────────────────────────


def test_config_bare_shows_tiers(runner, monkeypatch):
    """oikos config bare shows Essential and Advanced headers."""
    _mock_settings(monkeypatch)
    result = runner.invoke(main, ["config"])
    assert result.exit_code == 0
    assert "Essential" in result.output
    assert "Advanced" in result.output


def test_config_write_essential(runner, monkeypatch):
    """oikos config cloud_routing_posture conservative writes successfully."""
    _mock_settings(monkeypatch)
    result = runner.invoke(main, ["config", "cloud_routing_posture", "conservative"])
    assert result.exit_code == 0
    assert "saved" in result.output.lower() or "conservative" in result.output


def test_config_advanced_redirect(runner, monkeypatch):
    """oikos config pii_confidence_threshold 0.8 prints redirect."""
    _mock_settings(monkeypatch)
    result = runner.invoke(main, ["config", "pii_confidence_threshold", "0.8"])
    assert "Advanced" in result.output or "TUI" in result.output


def test_config_expert_direct_write(runner, monkeypatch):
    """oikos config cosine_sensitivity 0.8 writes directly."""
    _mock_settings(monkeypatch)
    result = runner.invoke(main, ["config", "cosine_sensitivity", "0.8"])
    assert result.exit_code == 0
    assert "saved" in result.output.lower() or "0.8" in result.output


def _mock_settings(monkeypatch):
    """Isolate settings for CLI tests."""
    from core.interface.settings_registry import SETTINGS_REGISTRY

    store = {k: v.default for k, v in SETTINGS_REGISTRY.items()}

    def fake_get(key):
        if key in store:
            return store[key]
        raise KeyError(f"Unknown setting: {key}")

    def fake_update(key, value):
        from core.interface.settings import _coerce
        from core.interface.settings_registry import validate_setting

        defn = SETTINGS_REGISTRY[key]
        value = _coerce(value, defn.setting_type)
        ok, msg = validate_setting(key, value)
        if not ok:
            raise ValueError(msg)
        store[key] = value
        return {"applied": True, "restart_required": defn.restart_required}

    def fake_tiered():
        from core.interface.settings_registry import SettingTier

        tiers = {"essential": {}, "advanced": {}, "expert": {}}
        for k, defn in SETTINGS_REGISTRY.items():
            val = store.get(k, defn.default)
            tiers[defn.tier.value][k] = defn.to_api_dict(val)
        return tiers

    monkeypatch.setattr("core.interface.settings.get_setting", fake_get)
    monkeypatch.setattr("core.interface.settings.update_setting", fake_update)
    monkeypatch.setattr("core.interface.settings.get_tiered_settings", fake_tiered)
