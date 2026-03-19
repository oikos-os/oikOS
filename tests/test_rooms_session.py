"""Tests for per-Room session storage (Phase 8b, Task 2)."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    """Isolate session + room state for every test."""
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    rooms_dir = tmp_path / "rooms"
    rooms_dir.mkdir()
    state_file = sessions_dir / ".current_session.json"

    monkeypatch.setattr("core.memory.session.SESSIONS_DIR", sessions_dir)
    monkeypatch.setattr("core.memory.session.SESSION_STATE_FILE", state_file)
    monkeypatch.setattr("core.interface.config.ROOMS_DIR", rooms_dir)

    # Reset singletons
    from core.rooms.manager import reset_room_manager
    reset_room_manager()

    # Re-init manager with tmp rooms dir so Home is created
    from core.rooms.manager import get_room_manager
    get_room_manager(rooms_dir=rooms_dir)

    yield

    reset_room_manager()


def _create_room(room_id: str, name: str, session_isolation: bool = True):
    from core.rooms.manager import get_room_manager
    from core.rooms.models import RoomConfig

    mgr = get_room_manager()
    room = RoomConfig(
        id=room_id,
        name=name,
        limits={"session_isolation": session_isolation},
    )
    mgr.create_room(room)
    return room


def _switch_room(room_id: str):
    from core.rooms.manager import get_room_manager
    get_room_manager().switch_room(room_id)


def _force_new_session():
    """Delete state file to force a new session on next call."""
    from core.memory.session import SESSION_STATE_FILE
    if SESSION_STATE_FILE.exists():
        SESSION_STATE_FILE.unlink()


def test_session_includes_room_id():
    """New sessions include room_id field."""
    from core.memory.session import get_or_create_session

    _force_new_session()
    state = get_or_create_session()
    assert "room_id" in state
    assert state["room_id"] == "home"


def test_custom_room_session_in_room_dir(tmp_path, monkeypatch):
    """Sessions in a custom room log to sessions/{room_id}/YYYY-MM-DD/."""
    from core.memory.session import SESSIONS_DIR, get_or_create_session, log_interaction

    _create_room("research", "Research")
    _switch_room("research")
    _force_new_session()

    state = get_or_create_session()
    assert state["room_id"] == "research"

    log_interaction(
        session_id=state["session_id"],
        session_started_at=state["started_at"],
        query_hash="abc123",
        query="test query",
        room_id=state["room_id"],
    )

    # Verify file landed in sessions/research/YYYY-MM-DD/
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    expected = SESSIONS_DIR / "research" / today / f"SESSION-{state['session_id']}.jsonl"
    assert expected.exists()

    # Verify NOT in sessions/home/
    home_dir = SESSIONS_DIR / "home" / today
    assert not home_dir.exists() or not list(home_dir.glob(f"SESSION-{state['session_id']}*"))


def test_list_sessions_filters_by_room():
    """list_recent_sessions with room_id only returns that room's sessions."""
    from core.memory.session import SESSIONS_DIR, list_recent_sessions

    _create_room("work", "Work")
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Seed home session
    home_dir = SESSIONS_DIR / "home" / today
    home_dir.mkdir(parents=True)
    (home_dir / "SESSION-aaa_summary.json").write_text(json.dumps({
        "session_id": "aaa",
        "started_at": "2026-03-18T10:00:00+00:00",
        "first_query": "home query",
        "routes": {"local": 1, "cloud": 0},
    }))

    # Seed work session
    work_dir = SESSIONS_DIR / "work" / today
    work_dir.mkdir(parents=True)
    (work_dir / "SESSION-bbb_summary.json").write_text(json.dumps({
        "session_id": "bbb",
        "started_at": "2026-03-18T11:00:00+00:00",
        "first_query": "work query",
        "routes": {"local": 1, "cloud": 0},
    }))

    # Filtered: only work
    work_sessions = list_recent_sessions(room_id="work")
    assert len(work_sessions) == 1
    assert work_sessions[0]["session_id"] == "bbb"

    # Unfiltered: both
    all_sessions = list_recent_sessions()
    assert len(all_sessions) == 2


def test_home_sees_all_when_isolation_off():
    """Home room (session_isolation=False) sees sessions from all rooms."""
    from core.memory.session import SESSIONS_DIR, list_recent_sessions

    _create_room("lab", "Lab")
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Seed sessions in two rooms
    for room, sid, query in [("home", "h1", "home q"), ("lab", "l1", "lab q")]:
        d = SESSIONS_DIR / room / today
        d.mkdir(parents=True)
        (d / f"SESSION-{sid}_summary.json").write_text(json.dumps({
            "session_id": sid,
            "started_at": "2026-03-18T10:00:00+00:00",
            "first_query": query,
            "routes": {"local": 1, "cloud": 0},
        }))

    # Home has session_isolation=False, so passing room_id="home" should show all
    sessions = list_recent_sessions(room_id="home")
    sids = {s["session_id"] for s in sessions}
    assert sids == {"h1", "l1"}


def test_find_session_jsonl_across_rooms():
    """_find_session_jsonl locates sessions in the room/date hierarchy."""
    from core.memory.session import SESSIONS_DIR, _find_session_jsonl

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    target_dir = SESSIONS_DIR / "deep" / today
    target_dir.mkdir(parents=True)

    log_file = target_dir / "SESSION-xyz123.jsonl"
    log_file.write_text(json.dumps({"type": "query", "query": "test"}) + "\n")

    result = _find_session_jsonl("xyz123")
    assert result is not None
    assert result == log_file


def test_load_session_transcript_across_rooms():
    """load_session_transcript finds sessions in room/date hierarchy."""
    from core.memory.session import SESSIONS_DIR, load_session_transcript

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    target_dir = SESSIONS_DIR / "research" / today
    target_dir.mkdir(parents=True)

    entry = {"type": "query", "query": "deep research"}
    (target_dir / "SESSION-tr123.jsonl").write_text(json.dumps(entry) + "\n")

    transcript = load_session_transcript("tr123")
    assert len(transcript) == 1
    assert transcript[0]["query"] == "deep research"


# ── Consolidation Room-Scoping (Task 6) ─────────────────────────────


def _make_proposal(proposal_id: str, room_id: str = "home", status: str = "pending") -> str:
    """Build a PromotionProposal JSON line."""
    from core.interface.models import PromotionProposal

    p = PromotionProposal(
        proposal_id=proposal_id,
        source_session_ids=["test-session"],
        insight_type="fact",
        action="CREATE",
        summary="test proposal",
        draft_content="test content",
        target_path="vault/knowledge/test.md",
        heuristics_triggered=["test"],
        room_id=room_id,
        status=status,
        created_at="2026-03-18T12:00:00+00:00",
    )
    return p.model_dump_json()


def test_consolidation_proposals_include_room_id(tmp_path, monkeypatch):
    """Verify room_id field exists on PromotionProposal."""
    from core.interface.models import PromotionProposal

    proposals_log = tmp_path / "proposals.jsonl"
    proposals_log.write_text(_make_proposal("p1", room_id="research") + "\n")
    monkeypatch.setattr("core.agency.consolidation.CONSOLIDATION_PROPOSALS_LOG", proposals_log)

    from core.agency.consolidation import load_pending_proposals

    results = load_pending_proposals(room_id="research")
    assert len(results) == 1
    assert results[0].room_id == "research"
    assert results[0].proposal_id == "p1"


def test_consolidation_proposals_filtered_by_room(tmp_path, monkeypatch):
    """Verify only matching Room's proposals are returned."""
    proposals_log = tmp_path / "proposals.jsonl"
    lines = "\n".join([
        _make_proposal("p-home", room_id="home"),
        _make_proposal("p-work", room_id="work"),
        _make_proposal("p-work2", room_id="work"),
        _make_proposal("p-rejected", room_id="work", status="rejected"),
    ])
    proposals_log.write_text(lines + "\n")
    monkeypatch.setattr("core.agency.consolidation.CONSOLIDATION_PROPOSALS_LOG", proposals_log)

    from core.agency.consolidation import load_pending_proposals

    # Only pending work proposals
    work = load_pending_proposals(room_id="work")
    assert len(work) == 2
    assert all(p.room_id == "work" for p in work)

    # Only pending home proposals
    home = load_pending_proposals(room_id="home")
    assert len(home) == 1
    assert home[0].proposal_id == "p-home"
