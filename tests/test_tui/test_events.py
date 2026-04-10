"""Tests for event-to-human translation."""
from core.interface.tui.events import translate_events


def test_empty_events():
    assert translate_events([]) == []


def test_inference_events_become_chat():
    events = [
        {"timestamp": "2026-03-25T15:33:00", "category": "inference", "type": "complete",
         "data": {"room": "Home"}},
    ]
    result = translate_events(events)
    assert len(result) == 1
    assert "Chatted in Home" in result[0]["text"]


def test_vault_index_event():
    events = [
        {"timestamp": "2026-03-25T11:30:00", "category": "vault", "type": "index_complete",
         "data": {"file_count": 247}},
    ]
    result = translate_events(events)
    assert len(result) == 1
    assert "Vault indexed" in result[0]["text"]
    assert "247" in result[0]["text"]


def test_room_create_event():
    events = [
        {"timestamp": "2026-03-25T12:00:00", "category": "room", "type": "create",
         "data": {"name": "Writing"}},
    ]
    result = translate_events(events)
    assert "Writing" in result[0]["text"]


def test_room_switch_event():
    events = [
        {"timestamp": "2026-03-25T14:00:00", "category": "room", "type": "switch",
         "data": {"name": "Code"}},
    ]
    result = translate_events(events)
    assert "Switched to Code" in result[0]["text"]


def test_fsm_events_skipped():
    events = [
        {"timestamp": "2026-03-25T14:00:00", "category": "fsm", "type": "transition"},
        {"timestamp": "2026-03-25T14:01:00", "category": "embedded", "type": "start"},
    ]
    result = translate_events(events)
    assert len(result) == 0


def test_max_5_entries():
    events = [
        {"timestamp": f"2026-03-25T{10+i}:00:00", "category": "room", "type": "switch",
         "data": {"name": f"Room{i}"}}
        for i in range(10)
    ]
    result = translate_events(events)
    assert len(result) == 5


def test_time_format_12h():
    events = [
        {"timestamp": "2026-03-25T15:33:00", "category": "inference", "type": "complete",
         "data": {"room": "Home"}},
    ]
    result = translate_events(events)
    assert result[0]["time"] == " 3:33 PM"


def test_consolidation_event():
    events = [
        {"timestamp": "2026-03-25T10:00:00", "category": "agent", "type": "consolidation_complete"},
    ]
    result = translate_events(events)
    assert result[0]["text"] == "Memory consolidated"


def test_daemon_auto_close_event():
    events = [
        {"timestamp": "2026-03-25T10:00:00", "category": "daemon", "type": "session_auto_close",
         "data": {"room": "Home"}},
    ]
    result = translate_events(events)
    assert "Session auto-closed" in result[0]["text"]


def test_research_queue_event():
    events = [
        {"timestamp": "2026-03-25T10:00:00", "category": "research", "type": "queue",
         "data": {"topic": "local AI benchmarks"}},
    ]
    result = translate_events(events)
    assert "Research queued" in result[0]["text"]
    assert "local AI benchmarks" in result[0]["text"]


def test_inference_start_skipped():
    """inference/start events are skipped — only complete events show."""
    events = [
        {"timestamp": "2026-03-25T15:33:00", "category": "inference", "type": "start",
         "data": {"route": "local", "query_hash": "abc123"}},
    ]
    assert translate_events(events) == []


def test_inference_complete_no_room_shows_model():
    """When room is missing, show model name instead."""
    events = [
        {"timestamp": "2026-03-25T15:33:00", "category": "inference", "type": "complete",
         "data": {"route": "local", "model": "qwen2.5:14b", "confidence": 95.0}},
    ]
    result = translate_events(events)
    assert len(result) == 1
    assert "Queried qwen2.5:14b" in result[0]["text"]


def test_inference_complete_no_room_no_model():
    """When both room and model are missing, show generic text."""
    events = [
        {"timestamp": "2026-03-25T15:33:00", "category": "inference", "type": "complete",
         "data": {"route": "local"}},
    ]
    result = translate_events(events)
    assert result[0]["text"] == "Queried"
