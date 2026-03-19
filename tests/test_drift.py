"""Tests for drift detector — three-tier escalation nudge generation."""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from core.autonomic.drift import (
    DEADLINE_HORIZON_DAYS,
    INACTIVITY_THRESHOLD_DAYS,
    _build_domain_keyword_map,
    _days_since_domain_activity,
    _find_failure_pattern,
    _infer_domain_for_deadline,
    _load_escalation_state,
    _parse_deadline,
    _pattern_id,
    _save_escalation_state,
    drift_diagnostic,
    generate_nudges,
    get_session_activity,
    is_suppressed,
    parse_goals_deadlines,
    parse_projects,
    record_dismissal,
)
from core.interface.models import EscalationTier


def _now():
    return datetime.now(timezone.utc)


def _setup_projects(tmp_path):
    """Create a PROJECTS.md for domain keyword extraction."""
    identity_dir = tmp_path / "identity"
    identity_dir.mkdir(parents=True, exist_ok=True)
    projects = identity_dir / "PROJECTS.md"
    projects.write_text(
        "# PROJECTS\n"
        "## 1. PROJECT EXAMPLE PROJECT (THE LABEL)\n"
        "## 2. PROJECT OIKOS (THE BRAIN)\n"
        "## 3. PROJECT EXAMPLE NOVEL (THE FRANCHISE)\n"
        "## 4. PROJECT APRICOT (THE AUTOMATON)\n",
        encoding="utf-8",
    )
    return projects


def _setup_goals(tmp_path, days_until=10, status="PRODUCTION"):
    """Create a GOALS.md with a deadline days_until from now."""
    identity_dir = tmp_path / "identity"
    identity_dir.mkdir(parents=True, exist_ok=True)

    deadline_date = _now() + timedelta(days=days_until)
    month_abbr = deadline_date.strftime("%b")
    day = deadline_date.day

    goals = identity_dir / "GOALS.md"
    goals.write_text(
        f"| **{month_abbr} {day}** | BOY | *Secrets* | **{status}** |\n",
        encoding="utf-8",
    )
    return goals


def _setup_oikos_logs(tmp_path, days=3, music_days_ago=None):
    """Create session logs showing only OIKOS work for the past N days.

    If music_days_ago is set, also create a example project session that many days ago.
    """
    logs_dir = tmp_path / "sessions"
    logs_dir.mkdir(parents=True, exist_ok=True)
    for i in range(days):
        date = (_now() - timedelta(days=i)).strftime("%Y-%m-%d")
        log_file = logs_dir / f"{date}_KP-CLAUDE.md"
        log_file.write_text("# Session\nWorked on OIKOS Python code.", encoding="utf-8")

    if music_days_ago is not None:
        date = (_now() - timedelta(days=music_days_ago)).strftime("%Y-%m-%d")
        log_file = logs_dir / f"{date}_music.md"
        log_file.write_text("# Session\nWorked on example project production.", encoding="utf-8")

    return logs_dir


# ── Deadline parsing ─────────────────────────────────────────────────


def test_parse_deadline_short_month():
    dt = _parse_deadline("Feb 27", year=2026)
    assert dt is not None
    assert dt.month == 2
    assert dt.day == 27


def test_parse_deadline_invalid():
    assert _parse_deadline("not a date") is None


# ── GOALS.md parsing ─────────────────────────────────────────────────


def test_parse_goals_deadlines(tmp_path):
    goals = tmp_path / "GOALS.md"
    goals.write_text(
        "# GOALS\n"
        "| Date | Artist | Track | Status |\n"
        "|---|---|---|---|\n"
        "| **Feb 27** | Vossa | *Horas* | **LOCKED** |\n"
        "| **Mar 27** | BOY | *Secrets* | **PRODUCTION** |\n"
        "| **Jan 30** | George | *Lovebyte* | **RELEASED** |\n",
        encoding="utf-8",
    )
    deadlines = parse_goals_deadlines(goals)
    assert len(deadlines) == 3
    assert deadlines[0]["track"] == "Horas"
    assert deadlines[0]["status"] == "LOCKED"
    assert deadlines[2]["status"] == "RELEASED"


def test_parse_goals_missing_file():
    assert parse_goals_deadlines(Path("/nonexistent/GOALS.md")) == []


# ── PROJECTS.md parsing ──────────────────────────────────────────────


def test_parse_projects(tmp_path):
    projects = tmp_path / "PROJECTS.md"
    projects.write_text(
        "# PROJECTS\n"
        "## 1. PROJECT EXAMPLE PROJECT (THE LABEL)\n"
        "## 2. PROJECT OIKOS (THE BRAIN)\n"
        "## 3. PROJECT EXAMPLE NOVEL (THE FRANCHISE)\n",
        encoding="utf-8",
    )
    result = parse_projects(projects)
    assert len(result) == 3
    assert result[0]["name"] == "EXAMPLE PROJECT"
    assert result[0]["keywords"] == {"trendy", "decay"}
    assert result[1]["name"] == "OIKOS"


def test_parse_projects_generates_keywords(tmp_path):
    projects = tmp_path / "PROJECTS.md"
    projects.write_text(
        "## 1. PROJECT EXAMPLE NOVEL (THE FRANCHISE)\n",
        encoding="utf-8",
    )
    result = parse_projects(projects)
    assert result[0]["keywords"] == {"arcadia", "heights"}


# ── Domain keyword map ───────────────────────────────────────────────


def test_build_domain_keyword_map(tmp_path):
    _setup_projects(tmp_path)
    domain_map = _build_domain_keyword_map(tmp_path / "identity" / "PROJECTS.md")
    assert "example project" in domain_map
    assert "trendy" in domain_map["example project"]
    assert "oikos" in domain_map


def test_build_domain_keyword_map_missing_file():
    domain_map = _build_domain_keyword_map(Path("/nonexistent/PROJECTS.md"))
    # Should still have oikos as default
    assert "oikos" in domain_map


# ── Domain inference for deadlines ───────────────────────────────────


def test_infer_domain_by_track_keyword():
    domain_map = {"example project": {"trendy", "decay", "horas"}}
    dl = {"project": "Vossa", "track": "Horas"}
    assert _infer_domain_for_deadline(dl, domain_map) == "example project"


def test_infer_domain_fallback_music():
    domain_map = {"example project": {"trendy", "decay"}, "oikos": {"oikos"}}
    dl = {"project": "Unknown Artist", "track": "New Song"}
    # No keyword match, but "trendy" in domain name -> fallback
    assert _infer_domain_for_deadline(dl, domain_map) == "example project"


def test_infer_domain_returns_none():
    domain_map = {"oikos": {"oikos"}}  # No music-like domain
    dl = {"project": "Unknown", "track": "Song"}
    assert _infer_domain_for_deadline(dl, domain_map) is None


# ── Session activity ─────────────────────────────────────────────────


def test_get_session_activity_uses_domain_map(tmp_path):
    today = _now().strftime("%Y-%m-%d")
    log_file = tmp_path / f"{today}_KP-CLAUDE.md"
    log_file.write_text("# Session\nWorked on example project stuff.", encoding="utf-8")

    domain_map = {"example project": {"trendy", "decay"}, "oikos": {"oikos"}}
    with patch("core.autonomic.drift.LOGS_DIR", tmp_path):
        activity = get_session_activity(domain_map=domain_map)

    assert len(activity) >= 1
    assert "example project" in activity[0]["domain_hints"]
    assert "oikos" in activity[0]["domain_hints"]


def test_get_session_activity_empty_dir(tmp_path):
    with patch("core.autonomic.drift.LOGS_DIR", tmp_path):
        activity = get_session_activity()
    assert activity == []


# ── Domain activity tracking ─────────────────────────────────────────


def test_days_since_domain_activity_found():
    activity = [
        {"date": _now() - timedelta(days=2), "source": "test", "domain_hints": {"oikos"}},
        {"date": _now() - timedelta(days=5), "source": "test", "domain_hints": {"example project"}},
    ]
    days = _days_since_domain_activity(activity, "example project")
    assert days is not None
    assert 4 <= days <= 6


def test_days_since_domain_activity_not_found():
    activity = [
        {"date": _now() - timedelta(days=1), "source": "test", "domain_hints": {"oikos"}},
    ]
    days = _days_since_domain_activity(activity, "example project")
    assert days is None


# ── Nudge generation (basic, adapted from Phase 5) ──────────────────


def test_generate_nudges_detects_drift(tmp_path):
    """Deadline approaching + music inactive 4 days + OIKOS focus -> NUDGE."""
    _setup_goals(tmp_path)
    _setup_projects(tmp_path)
    logs_dir = _setup_oikos_logs(tmp_path, music_days_ago=4)

    state_file = tmp_path / "escalation" / "state.json"

    with (
        patch("core.autonomic.drift.VAULT_DIR", tmp_path),
        patch("core.autonomic.drift.LOGS_DIR", logs_dir),
    ):
        nudges = generate_nudges(vault_dir=tmp_path, state_file=state_file)

    assert len(nudges) >= 1
    assert "Secrets" in nudges[0].message
    assert "Tinker" in nudges[0].message
    assert nudges[0].tier == EscalationTier.NUDGE


def test_generate_nudges_no_drift_when_active(tmp_path):
    """Deadline approaching but music activity recent -> no nudge."""
    _setup_goals(tmp_path)
    _setup_projects(tmp_path)

    logs_dir = tmp_path / "sessions"
    logs_dir.mkdir(parents=True)
    today = _now().strftime("%Y-%m-%d")
    log_file = logs_dir / f"{today}_KP-CLAUDE.md"
    log_file.write_text("# Session\nWorked on example project music production.", encoding="utf-8")

    with (
        patch("core.autonomic.drift.VAULT_DIR", tmp_path),
        patch("core.autonomic.drift.LOGS_DIR", logs_dir),
    ):
        nudges = generate_nudges()

    assert len(nudges) == 0


def test_generate_nudges_skips_released(tmp_path):
    """Released items don't generate nudges even if deadline is near."""
    _setup_goals(tmp_path, days_until=5, status="RELEASED")
    _setup_projects(tmp_path)
    logs_dir = tmp_path / "sessions"
    logs_dir.mkdir(parents=True)

    with (
        patch("core.autonomic.drift.VAULT_DIR", tmp_path),
        patch("core.autonomic.drift.LOGS_DIR", logs_dir),
    ):
        nudges = generate_nudges()

    assert len(nudges) == 0


# ── Three-tier escalation tests (Phase 6a.2) ────────────────────────


def test_nudge_tier_assignment_basic(tmp_path):
    """4d inactivity with no pattern -> NUDGE tier."""
    _setup_goals(tmp_path)
    _setup_projects(tmp_path)
    logs_dir = _setup_oikos_logs(tmp_path, music_days_ago=4)

    state_file = tmp_path / "escalation" / "state.json"

    with (
        patch("core.autonomic.drift.VAULT_DIR", tmp_path),
        patch("core.autonomic.drift.LOGS_DIR", logs_dir),
    ):
        nudges = generate_nudges(vault_dir=tmp_path, state_file=state_file)

    assert len(nudges) >= 1
    assert nudges[0].tier == EscalationTier.NUDGE


def test_advisory_requires_pattern_match(tmp_path):
    """8d inactivity but no failure pattern -> stays NUDGE."""
    _setup_goals(tmp_path)
    _setup_projects(tmp_path)

    # No LEARNED.md or CHALLENGES.md -> no pattern match
    # Music activity 8 days ago (> ADVISORY_DAYS=7 but no pattern)
    logs_dir = _setup_oikos_logs(tmp_path, music_days_ago=8)

    state_file = tmp_path / "escalation" / "state.json"

    with (
        patch("core.autonomic.drift.VAULT_DIR", tmp_path),
        patch("core.autonomic.drift.LOGS_DIR", logs_dir),
    ):
        nudges = generate_nudges(vault_dir=tmp_path, state_file=state_file)

    assert len(nudges) >= 1
    assert nudges[0].tier == EscalationTier.NUDGE  # no pattern file -> stays NUDGE


def test_advisory_with_pattern_match(tmp_path):
    """8d inactivity + failure pattern in LEARNED.md -> ADVISORY."""
    _setup_goals(tmp_path)
    _setup_projects(tmp_path)

    # Create LEARNED.md with failure pattern for example project
    identity_dir = tmp_path / "identity"
    learned = identity_dir / "LEARNED.md"
    learned.write_text("- Example Project releases often stall due to mastering delays.\n", encoding="utf-8")

    # Music activity 8 days ago (>7 ADVISORY, <14 INTERVENTION)
    logs_dir = _setup_oikos_logs(tmp_path, music_days_ago=8)

    state_file = tmp_path / "escalation" / "state.json"

    with (
        patch("core.autonomic.drift.VAULT_DIR", tmp_path),
        patch("core.autonomic.drift.LOGS_DIR", logs_dir),
    ):
        nudges = generate_nudges(vault_dir=tmp_path, state_file=state_file)

    assert len(nudges) >= 1
    assert nudges[0].tier == EscalationTier.ADVISORY
    assert "Pattern" in nudges[0].message


def test_intervention_on_long_inactivity(tmp_path):
    """14+ days inactivity -> INTERVENTION."""
    _setup_goals(tmp_path)
    _setup_projects(tmp_path)

    # Empty logs -> None inactivity (treated as 999)
    logs_dir = tmp_path / "sessions"
    logs_dir.mkdir(parents=True)

    state_file = tmp_path / "escalation" / "state.json"

    with (
        patch("core.autonomic.drift.VAULT_DIR", tmp_path),
        patch("core.autonomic.drift.LOGS_DIR", logs_dir),
    ):
        nudges = generate_nudges(vault_dir=tmp_path, state_file=state_file)

    assert len(nudges) >= 1
    assert nudges[0].tier == EscalationTier.INTERVENTION
    assert "INTERVENTION REQUIRED" in nudges[0].message


def test_dismissal_promotes_nudge_to_advisory(tmp_path):
    """2 unreasoned dismissals at NUDGE level promotes to ADVISORY (progressive)."""
    _setup_goals(tmp_path)
    _setup_projects(tmp_path)
    logs_dir = _setup_oikos_logs(tmp_path, music_days_ago=4)

    state_file = tmp_path / "escalation" / "state.json"

    pid = _pattern_id("example project", "Secrets")
    state = {"patterns": {pid: {
        "times_surfaced": 2,
        "times_dismissed": 2,
        "unreasoned_dismissals": 2,
        "last_reason": None,
        "suppressed": False,
    }}}
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text(json.dumps(state), encoding="utf-8")

    with (
        patch("core.autonomic.drift.VAULT_DIR", tmp_path),
        patch("core.autonomic.drift.LOGS_DIR", logs_dir),
    ):
        nudges = generate_nudges(vault_dir=tmp_path, state_file=state_file)

    assert len(nudges) >= 1
    # Progressive: NUDGE + 2 unreasoned dismissals = ADVISORY (not INTERVENTION)
    assert nudges[0].tier == EscalationTier.ADVISORY


# ── Escalation state persistence ─────────────────────────────────────


def test_escalation_state_persistence(tmp_path):
    state_file = tmp_path / "escalation" / "state.json"
    state = {"patterns": {"abc123": {
        "times_surfaced": 1, "times_dismissed": 0,
        "unreasoned_dismissals": 0, "last_reason": None, "suppressed": False,
    }}}
    _save_escalation_state(state, state_file)

    loaded = _load_escalation_state(state_file)
    assert loaded["patterns"]["abc123"]["times_surfaced"] == 1


def test_record_dismissal_with_reason(tmp_path):
    state_file = tmp_path / "escalation" / "state.json"
    record_dismissal("test_id", reason="Working on stems", state_file=state_file)

    state = _load_escalation_state(state_file)
    entry = state["patterns"]["test_id"]
    assert entry["times_dismissed"] == 1
    assert entry["unreasoned_dismissals"] == 0
    assert entry["last_reason"] == "Working on stems"


def test_record_dismissal_without_reason(tmp_path):
    state_file = tmp_path / "escalation" / "state.json"
    record_dismissal("test_id", reason=None, state_file=state_file)

    state = _load_escalation_state(state_file)
    entry = state["patterns"]["test_id"]
    assert entry["times_dismissed"] == 1
    assert entry["unreasoned_dismissals"] == 1


def test_suppression_after_threshold(tmp_path):
    state_file = tmp_path / "escalation" / "state.json"
    for _ in range(3):
        record_dismissal("test_id", reason=None, state_file=state_file)

    assert is_suppressed("test_id", state_file) is True


def test_suppressed_nudge_not_emitted(tmp_path):
    """Suppressed patterns excluded from results."""
    _setup_goals(tmp_path)
    _setup_projects(tmp_path)
    logs_dir = _setup_oikos_logs(tmp_path, music_days_ago=4)

    state_file = tmp_path / "escalation" / "state.json"

    # Suppress the pattern that would match
    pid = _pattern_id("example project", "Secrets")
    state = {"patterns": {pid: {
        "times_surfaced": 5,
        "times_dismissed": 3,
        "unreasoned_dismissals": 3,
        "last_reason": None,
        "suppressed": True,
    }}}
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text(json.dumps(state), encoding="utf-8")

    with (
        patch("core.autonomic.drift.VAULT_DIR", tmp_path),
        patch("core.autonomic.drift.LOGS_DIR", logs_dir),
    ):
        nudges = generate_nudges(vault_dir=tmp_path, state_file=state_file)

    assert len(nudges) == 0


# ── Failure pattern search ───────────────────────────────────────────


def test_find_failure_pattern_match(tmp_path):
    identity_dir = tmp_path / "identity"
    identity_dir.mkdir(parents=True, exist_ok=True)
    learned = identity_dir / "LEARNED.md"
    learned.write_text("- Example project releases often stall when mastering.\n", encoding="utf-8")

    result = _find_failure_pattern("example project", vault_dir=tmp_path)
    assert result is not None
    assert "stall" in result


def test_find_failure_pattern_no_match(tmp_path):
    identity_dir = tmp_path / "identity"
    identity_dir.mkdir(parents=True, exist_ok=True)
    learned = identity_dir / "LEARNED.md"
    learned.write_text("- Music production is fun.\n", encoding="utf-8")

    result = _find_failure_pattern("example project", vault_dir=tmp_path)
    assert result is None


# ── Diagnostic ───────────────────────────────────────────────────────


def test_drift_diagnostic(tmp_path):
    identity_dir = tmp_path / "identity"
    identity_dir.mkdir(parents=True)

    goals = identity_dir / "GOALS.md"
    goals.write_text(
        "| **Feb 27** | Vossa | *Horas* | **LOCKED** |\n"
        "| **Jan 30** | George | *Lovebyte* | **RELEASED** |\n",
        encoding="utf-8",
    )

    _setup_projects(tmp_path)

    with patch("core.autonomic.drift.VAULT_DIR", tmp_path):
        diag = drift_diagnostic()

    assert diag["total_deadlines"] == 2
    assert diag["active_deadlines"] == 1  # only Horas (LOCKED), not Lovebyte (RELEASED)
    assert diag["domains_tracked"] >= 2


def test_drift_diagnostic_no_deadlines(tmp_path):
    identity_dir = tmp_path / "identity"
    identity_dir.mkdir(parents=True)

    goals = identity_dir / "GOALS.md"
    goals.write_text("# GOALS\nNo deadlines here.\n", encoding="utf-8")

    _setup_projects(tmp_path)

    with patch("core.autonomic.drift.VAULT_DIR", tmp_path):
        diag = drift_diagnostic()

    assert diag["total_deadlines"] == 0
    assert diag["active_deadlines"] == 0
