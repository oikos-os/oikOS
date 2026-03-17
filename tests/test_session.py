"""Tests for session boundary management."""

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from core.memory.session import (
    SESSION_TIMEOUT_MINUTES,
    _is_expired,
    close_session,
    get_or_create_session,
    log_interaction,
)


def _now():
    return datetime.now(timezone.utc)


def _make_state(started_minutes_ago=5, last_active_minutes_ago=2, **overrides):
    now = _now()
    state = {
        "session_id": "test1234abcd5678",
        "started_at": (now - timedelta(minutes=started_minutes_ago)).isoformat(),
        "last_active_at": (now - timedelta(minutes=last_active_minutes_ago)).isoformat(),
        "timeout_minutes": SESSION_TIMEOUT_MINUTES,
        "interaction_count": 3,
    }
    state.update(overrides)
    return state


# ── Expiry logic ─────────────────────────────────────────────────────


def test_is_expired_false_within_timeout():
    state = _make_state(started_minutes_ago=5, last_active_minutes_ago=2)
    assert _is_expired(state) is False


def test_is_expired_true_inactivity():
    state = _make_state(last_active_minutes_ago=SESSION_TIMEOUT_MINUTES + 5)
    assert _is_expired(state) is True


def test_is_expired_true_new_day():
    yesterday = _now() - timedelta(days=1)
    state = _make_state()
    state["started_at"] = yesterday.isoformat()
    assert _is_expired(state) is True


# ── get_or_create_session ────────────────────────────────────────────


def test_create_new_session_when_no_state(tmp_path):
    state_file = tmp_path / ".current_session.json"
    with patch("core.memory.session.SESSION_STATE_FILE", state_file):
        state = get_or_create_session()

    assert "session_id" in state
    assert len(state["session_id"]) == 16
    assert state["interaction_count"] == 1
    assert state_file.exists()


def test_reuse_active_session(tmp_path):
    state_file = tmp_path / ".current_session.json"
    with patch("core.memory.session.SESSION_STATE_FILE", state_file):
        s1 = get_or_create_session()
        s2 = get_or_create_session()

    assert s1["session_id"] == s2["session_id"]
    assert s2["interaction_count"] == 2


def test_create_new_session_when_expired(tmp_path):
    state_file = tmp_path / ".current_session.json"
    expired_state = _make_state(last_active_minutes_ago=SESSION_TIMEOUT_MINUTES + 10)
    state_file.write_text(json.dumps(expired_state), encoding="utf-8")

    with patch("core.memory.session.SESSION_STATE_FILE", state_file):
        state = get_or_create_session()

    assert state["session_id"] != expired_state["session_id"]
    assert state["interaction_count"] == 1


def test_create_new_session_corrupt_file(tmp_path):
    state_file = tmp_path / ".current_session.json"
    state_file.write_text("not json", encoding="utf-8")

    with patch("core.memory.session.SESSION_STATE_FILE", state_file):
        state = get_or_create_session()

    assert "session_id" in state


# ── close_session ────────────────────────────────────────────────────


def test_close_session_removes_state(tmp_path):
    state_file = tmp_path / ".current_session.json"
    logs_dir = tmp_path

    with (
        patch("core.memory.session.SESSION_STATE_FILE", state_file),
        patch("core.memory.session.LOGS_DIR", logs_dir),
    ):
        get_or_create_session()
        assert state_file.exists()

        closed = close_session()

    assert closed is not None
    assert closed["close_reason"] == "explicit"
    assert not state_file.exists()


def test_close_session_no_active():
    with patch("core.memory.session._load_state", return_value=None):
        result = close_session()
    assert result is None


# ── log_interaction ──────────────────────────────────────────────────


def test_log_interaction_writes_jsonl(tmp_path):
    started_at = "2026-02-20T00:00:00+00:00"
    with patch("core.memory.session.SESSIONS_DIR", tmp_path):
        log_interaction("abc123", started_at, "qhash456", "test query")

    log_files = list(tmp_path.glob("**/*SESSION-abc123.jsonl"))
    assert len(log_files) == 1

    entry = json.loads(log_files[0].read_text(encoding="utf-8").strip())
    assert entry["session_id"] == "abc123"
    assert entry["query_hash"] == "qhash456"
    assert entry["query"] == "test query"
    assert entry["type"] == "query"


def test_log_interaction_appends(tmp_path):
    started_at = "2026-02-20T00:00:00+00:00"
    with patch("core.memory.session.SESSIONS_DIR", tmp_path):
        log_interaction("abc123", started_at, "q1", "first query")
        log_interaction("abc123", started_at, "q2", "second query")

    log_files = list(tmp_path.glob("**/*SESSION-abc123.jsonl"))
    lines = log_files[0].read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 2
