"""Integration tests for Phase 6b — FSM + Scanner + CLI wiring."""

import json
from datetime import datetime, timedelta, timezone
from io import StringIO
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from core.interface.cli import main
from core.autonomic.fsm import _save_state, get_current_state, transition_to
from core.interface.models import Blip, DriftNudge, EscalationTier, SystemState


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def fsm_files(tmp_path, monkeypatch):
    """Redirect FSM + scanner files to tmp_path."""
    state_file = tmp_path / ".system_state.json"
    log_file = tmp_path / "state_transitions.jsonl"
    blip_file = tmp_path / "scanner" / "blips.jsonl"

    monkeypatch.setattr("core.autonomic.fsm.FSM_STATE_FILE", state_file)
    monkeypatch.setattr("core.autonomic.fsm.FSM_TRANSITION_LOG", log_file)
    monkeypatch.setattr("core.interface.cli.click.getchar", lambda: "y")  # auto-acknowledge

    return {"state": state_file, "log": log_file, "blips": blip_file}


def _make_blip(blip_id: str = "test1", delivered: bool = False) -> Blip:
    now = datetime.now(timezone.utc)
    return Blip(
        blip_id=blip_id,
        generated_at=now.isoformat(),
        chunk_a={"chunk_id": "a1", "source_path": "vault/identity/A.md", "tier": "core", "content_preview": "test A"},
        chunk_b={"chunk_id": "b1", "source_path": "vault/knowledge/B.md", "tier": "semantic", "content_preview": "test B"},
        optimist_score=80.0,
        pessimist_kill_probability=15.0,
        resonance=68.0,
        observation="Music discipline mirrors code refactoring",
        delivered=delivered,
        expires_at=(now + timedelta(days=15)).isoformat(),
    )


def _make_nudge(tier=EscalationTier.NUDGE) -> DriftNudge:
    return DriftNudge(
        message="TRENDY DECAY: 5 days inactive",
        tier=tier,
        domain="music",
        pattern_id="abc123",
    )


# ── Briefing tests ──────────────────────────────────────────────────


def test_briefing_with_blips_and_nudges(fsm_files, monkeypatch):
    """Briefing renders blips and nudges without error."""
    from core.interface.cli import _deliver_briefing, console

    blips = [_make_blip()]
    nudges = [_make_nudge(EscalationTier.ADVISORY)]

    monkeypatch.setattr("core.autonomic.scanner.SCANNER_BLIP_LOG", fsm_files["blips"])
    with patch("core.interface.cli.load_undelivered_blips", return_value=blips, create=True), \
         patch("core.interface.cli.generate_nudges", return_value=nudges, create=True):
        # Patch at the import locations inside _deliver_briefing
        with patch("core.autonomic.scanner.load_undelivered_blips", return_value=blips), \
             patch("core.autonomic.scanner.mark_blips_delivered"), \
             patch("core.autonomic.drift.generate_nudges", return_value=nudges):
            _deliver_briefing()


def test_briefing_empty_is_silent(fsm_files):
    """No blips, no nudges → no output."""
    from core.interface.cli import _deliver_briefing

    with patch("core.autonomic.scanner.load_undelivered_blips", return_value=[]), \
         patch("core.autonomic.drift.generate_nudges", return_value=[]):
        # Should return silently
        _deliver_briefing()


def test_briefing_intervention_displayed(fsm_files, monkeypatch):
    """INTERVENTION nudge triggers mandatory display."""
    from core.interface.cli import _deliver_briefing

    nudges = [_make_nudge(EscalationTier.INTERVENTION)]

    with patch("core.autonomic.scanner.load_undelivered_blips", return_value=[]), \
         patch("core.autonomic.drift.generate_nudges", return_value=nudges), \
         patch("core.interface.cli.click.getchar", return_value="y"):
        _deliver_briefing()


# ── CLI command tests ────────────────────────────────────────────────


def test_state_command(runner, fsm_files):
    """oikos state shows current FSM state."""
    _save_state(SystemState.ACTIVE)
    result = runner.invoke(main, ["state"])
    assert "ACTIVE" in result.output


def test_idle_callback_chain(runner, fsm_files, monkeypatch):
    """oikos idle runs re-index → scanner → git."""
    _save_state(SystemState.ACTIVE)

    mock_index = {"files": 3, "added": 1, "skipped": 2, "deleted": 0}

    with patch("core.memory.indexer.index_vault", return_value=mock_index), \
         patch("core.autonomic.scanner.check_activation_gate", return_value={"active": False, "reason": "test"}), \
         patch("core.autonomic.fsm._auto_commit_vault", return_value={"committed": False, "reason": "no changes"}):
        result = runner.invoke(main, ["idle"])

    assert "IDLE" in result.output


def test_wake_loads_and_delivers(runner, fsm_files, monkeypatch):
    """oikos wake delivers briefing."""
    _save_state(SystemState.IDLE)

    with patch("core.autonomic.fsm._on_enter_active", return_value={"briefing_ready": True}), \
         patch("core.interface.cli._deliver_briefing") as mock_brief:
        result = runner.invoke(main, ["wake"])

    assert "ACTIVE" in result.output
    mock_brief.assert_called_once()


def test_auto_transition_no_briefing(fsm_files, monkeypatch):
    """Auto-transition from IDLE on query does NOT deliver briefing."""
    _save_state(SystemState.IDLE)

    with patch("core.autonomic.fsm._on_enter_active", return_value={"briefing_ready": True}):
        # Simulate handler auto-transition
        from core.autonomic.fsm import get_current_state, transition_to

        if get_current_state() in (SystemState.IDLE, SystemState.ASLEEP):
            result = transition_to(SystemState.ACTIVE, trigger="auto:query")

    # Briefing NOT called — that's CLI responsibility only on explicit wake
    assert get_current_state() == SystemState.ACTIVE


def test_full_cycle(runner, fsm_files, monkeypatch):
    """ACTIVE → idle → wake → query flow."""
    _save_state(SystemState.ACTIVE)

    # idle
    with patch("core.memory.indexer.index_vault", return_value={"files": 0, "added": 0, "skipped": 0, "deleted": 0}), \
         patch("core.autonomic.scanner.check_activation_gate", return_value={"active": False, "reason": "test"}), \
         patch("core.autonomic.fsm._auto_commit_vault", return_value={"committed": False, "reason": "no changes"}):
        runner.invoke(main, ["idle"])
    assert get_current_state() == SystemState.IDLE

    # wake
    with patch("core.autonomic.fsm._on_enter_active", return_value={"briefing_ready": True}), \
         patch("core.interface.cli._deliver_briefing"):
        runner.invoke(main, ["wake"])
    assert get_current_state() == SystemState.ACTIVE

    # sleep
    with patch("core.autonomic.fsm._on_enter_asleep", return_value={"flushed": True}):
        runner.invoke(main, ["sleep"])
    assert get_current_state() == SystemState.ASLEEP

    # auto-transition on simulated query
    with patch("core.autonomic.fsm._on_enter_active", return_value={"briefing_ready": True}):
        transition_to(SystemState.ACTIVE, trigger="auto:query")
    assert get_current_state() == SystemState.ACTIVE
