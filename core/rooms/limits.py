"""Per-Room limit enforcement and cost tracking."""
from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path

from core.interface.config import PROJECT_ROOT

log = logging.getLogger(__name__)
COSTS_DIR = PROJECT_ROOT / "logs" / "costs"
_cost_lock = threading.Lock()


def check_room_limits(room_id: str, tool_call_count: int = 0) -> dict:
    """Check current Room usage against limits. Returns enforcement actions."""
    try:
        from core.rooms.manager import get_room_manager
        room = get_room_manager().get_room(room_id)
    except ValueError:
        return {"enforce": False}

    limits = room.limits
    if not any([limits.max_tokens_per_query, limits.max_tool_calls_per_session, limits.monthly_cloud_budget_cents]):
        return {"enforce": False}

    result = {"enforce": True, "token_budget_override": None, "force_local": False, "block_tools": False}

    if limits.max_tokens_per_query:
        result["token_budget_override"] = limits.max_tokens_per_query

    if limits.max_tool_calls_per_session and tool_call_count >= limits.max_tool_calls_per_session:
        result["block_tools"] = True

    if limits.monthly_cloud_budget_cents:
        _, spent = _get_monthly_stats(room_id)
        if spent >= limits.monthly_cloud_budget_cents:
            result["force_local"] = True

    return result


def log_room_cost(room_id: str, provider: str, model: str, cost_usd: float, tokens: int) -> None:
    """Append a cost entry to the Room's cost log."""
    COSTS_DIR.mkdir(parents=True, exist_ok=True)
    log_file = COSTS_DIR / f"{room_id}.jsonl"
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "provider": provider, "model": model,
        "cost_usd": cost_usd, "tokens": tokens,
    }
    with _cost_lock:
        with log_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")


def get_room_usage(room_id: str) -> dict:
    """Get current month's usage stats for a Room."""
    monthly_tokens, monthly_spend_cents = _get_monthly_stats(room_id)
    return {"room_id": room_id, "monthly_cloud_spend_cents": monthly_spend_cents, "monthly_tokens": monthly_tokens}


def _get_monthly_stats(room_id: str) -> tuple[int, int]:
    log_file = COSTS_DIR / f"{room_id}.jsonl"
    if not log_file.exists():
        return 0, 0
    month_prefix = datetime.now(timezone.utc).strftime("%Y-%m")
    total_tokens = 0
    total_usd = 0.0
    for line in log_file.read_text(encoding="utf-8").splitlines():
        try:
            entry = json.loads(line)
            if entry.get("timestamp", "").startswith(month_prefix):
                total_usd += entry.get("cost_usd", 0.0)
                total_tokens += entry.get("tokens", 0)
        except json.JSONDecodeError:
            continue
    return total_tokens, int(total_usd * 100)


