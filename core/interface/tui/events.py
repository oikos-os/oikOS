"""Translate raw oikOS API events into human-readable journal entries."""
from datetime import datetime

_MAX_ENTRIES = 5


def _format_time(timestamp: str) -> str:
    dt = datetime.fromisoformat(timestamp)
    # Use %I (zero-padded 12h) then strip leading zero; %l is GNU-only and crashes on Windows
    hour = dt.strftime("%I").lstrip("0") or "12"
    return f"{hour}:{dt.strftime('%M %p')}".rjust(8)


def _translate(event: dict) -> str | None:
    category = event.get("category", "")
    etype = event.get("type", "")
    data = event.get("data") or {}

    key = f"{category}/{etype}"

    if key == "inference/complete":
        room = data.get("room", "")
        model = data.get("model", "")
        if room:
            count = data.get("message_count")
            if count is not None:
                return f"Chatted in {room} ({count} messages)"
            return f"Chatted in {room}"
        if model:
            return f"Queried {model}"
        return "Queried"

    if key == "agent/consolidation_complete":
        return "Memory consolidated"

    if key == "daemon/session_auto_close":
        mins = data.get("inactive_minutes")
        if mins:
            return f"Session auto-closed ({mins}m idle)"
        return "Session auto-closed"

    if key == "vault/index_complete":
        return f"Vault indexed ({data.get('file_count', 0)} files)"

    if key == "room/switch":
        return f"Switched to {data.get('name', '')}"

    if key == "room/create":
        return f"Room '{data.get('name', '')}' created"

    if key == "research/queue":
        return f"Research queued: {data.get('topic', '')}"

    if key == "research/complete":
        return f"Research complete: {data.get('topic', '')}"

    # fsm/transition, embedded/start, embedded/complete, and all others: skip
    return None


def translate_events(events: list[dict]) -> list[dict]:
    """Translate raw API events into lobby journal entries (max 5)."""
    result = []
    for event in events:
        text = _translate(event)
        if text is None:
            continue
        result.append({"time": _format_time(event.get("timestamp", "")), "text": text})
        if len(result) == _MAX_ENTRIES:
            break
    return result
