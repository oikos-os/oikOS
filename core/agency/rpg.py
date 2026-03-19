"""RPG Overlay — stats, XP, achievements derived from real system metrics.

Zero functional impact. If this module breaks, the system operates identically.
Persistence: logs/rpg/stats.json
"""

from __future__ import annotations

import json
import logging
import math
from datetime import datetime, timezone
from pathlib import Path

from core.interface.config import PROJECT_ROOT

log = logging.getLogger(__name__)

RPG_DIR = PROJECT_ROOT / "logs" / "rpg"
RPG_STATS_FILE = RPG_DIR / "stats.json"

# ── XP Rewards ────────────────────────────────────────────────────────
XP_REWARDS: dict[str, int] = {
    "test_pass": 10,
    "gauntlet_pass": 50,
    "vault_promotion": 25,
    "consolidation_review": 15,
    "eval_run": 30,
    "phase_certification": 500,
}

# ── Level Thresholds (geometric progression) ──────────────────────────
def xp_for_level(level: int) -> int:
    """XP required to reach a given level."""
    if level <= 1:
        return 0
    return int(100 * (1.5 ** (level - 1)))


def level_from_xp(total_xp: int) -> int:
    """Derive level from total XP."""
    level = 1
    while xp_for_level(level + 1) <= total_xp:
        level += 1
    return level


# ── Achievements ──────────────────────────────────────────────────────
ACHIEVEMENTS: list[dict] = [
    {"id": "crucible_survivor", "name": "Crucible Survivor", "trigger": "phase_7a_certified"},
    {"id": "iron_spine", "name": "Iron Spine", "trigger": "phase_7b_certified"},
    {"id": "the_face", "name": "The Face", "trigger": "phase_7c_certified"},
    {"id": "perfect_defense", "name": "Perfect Defense", "trigger": "gauntlet_perfect_5x"},
    {"id": "memory_keeper", "name": "Memory Keeper", "trigger": "vault_promotions_50"},
    {"id": "century", "name": "Century", "trigger": "tests_100"},
    {"id": "half_thousand", "name": "Half-Thousand", "trigger": "tests_500"},
    {"id": "first_blood", "name": "First Blood", "trigger": "first_gauntlet"},
]


# ── State ─────────────────────────────────────────────────────────────
def _default_state() -> dict:
    return {
        "total_xp": 0,
        "level": 1,
        "events_processed": 0,
        "achievements_unlocked": [],
        "counters": {
            "tests_passed": 0,
            "gauntlet_runs": 0,
            "gauntlet_perfect_streak": 0,
            "vault_promotions": 0,
            "eval_runs": 0,
            "consolidation_reviews": 0,
        },
        "last_updated": datetime.now(timezone.utc).isoformat(),
    }


def load_rpg_state() -> dict:
    """Load RPG state from disk."""
    if not RPG_STATS_FILE.exists():
        return _default_state()
    try:
        return json.loads(RPG_STATS_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return _default_state()


def save_rpg_state(state: dict) -> None:
    """Persist RPG state to disk."""
    RPG_DIR.mkdir(parents=True, exist_ok=True)
    state["last_updated"] = datetime.now(timezone.utc).isoformat()
    RPG_STATS_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")


# ── XP Grant ──────────────────────────────────────────────────────────
def grant_xp(event_type: str, state: dict | None = None) -> dict:
    """Grant XP for an event. Returns updated state."""
    if state is None:
        state = load_rpg_state()

    reward = XP_REWARDS.get(event_type, 0)
    if reward == 0:
        return state

    state["total_xp"] += reward
    state["level"] = level_from_xp(state["total_xp"])
    state["events_processed"] += 1

    # Update counters
    counters = state["counters"]
    if event_type == "test_pass":
        counters["tests_passed"] += 1
    elif event_type == "gauntlet_pass":
        counters["gauntlet_runs"] += 1
        counters["gauntlet_perfect_streak"] += 1
    elif event_type == "vault_promotion":
        counters["vault_promotions"] += 1
    elif event_type == "eval_run":
        counters["eval_runs"] += 1
    elif event_type == "consolidation_review":
        counters["consolidation_reviews"] += 1

    # Check achievements
    _check_achievements(state)

    save_rpg_state(state)
    return state


def record_gauntlet_imperfect(state: dict | None = None) -> dict:
    """Reset perfect gauntlet streak on imperfect run."""
    if state is None:
        state = load_rpg_state()
    state["counters"]["gauntlet_perfect_streak"] = 0
    save_rpg_state(state)
    return state


# ── Achievement Checks ────────────────────────────────────────────────
def _check_achievements(state: dict) -> None:
    unlocked = set(state["achievements_unlocked"])
    counters = state["counters"]

    checks = {
        "first_blood": counters["gauntlet_runs"] >= 1,
        "century": counters["tests_passed"] >= 100,
        "half_thousand": counters["tests_passed"] >= 500,
        "memory_keeper": counters["vault_promotions"] >= 50,
        "perfect_defense": counters["gauntlet_perfect_streak"] >= 5,
    }

    for achievement_id, condition in checks.items():
        if condition and achievement_id not in unlocked:
            unlocked.add(achievement_id)

    state["achievements_unlocked"] = sorted(unlocked)


def unlock_achievement(achievement_id: str, state: dict | None = None) -> dict:
    """Manually unlock an achievement (for phase certifications)."""
    if state is None:
        state = load_rpg_state()
    if achievement_id not in state["achievements_unlocked"]:
        state["achievements_unlocked"].append(achievement_id)
        state["achievements_unlocked"].sort()
        save_rpg_state(state)
    return state


# ── Stat Calculation ──────────────────────────────────────────────────
def calculate_stats(state: dict | None = None) -> dict:
    """Calculate character stats from real system metrics."""
    if state is None:
        state = load_rpg_state()

    counters = state["counters"]

    # Intelligence: test_count / 10 (capped at 100)
    intelligence = min(100, counters["tests_passed"] // 10)

    # Defense: gauntlet perfect streak * 20 (capped at 100)
    defense = min(100, counters["gauntlet_perfect_streak"] * 20)

    # Memory: vault_promotions * 2 (capped at 100)
    memory = min(100, counters["vault_promotions"] * 2)

    # Constitution: gauntlet_runs * 10 (proxy for uptime, capped at 100)
    constitution = min(100, counters["gauntlet_runs"] * 10)

    # Discipline: eval_runs * 15 (capped at 100)
    discipline = min(100, counters["eval_runs"] * 15)

    xp_current_level = xp_for_level(state["level"])
    xp_next_level = xp_for_level(state["level"] + 1)
    xp_progress = state["total_xp"] - xp_current_level
    xp_needed = max(1, xp_next_level - xp_current_level)

    return {
        "level": state["level"],
        "total_xp": state["total_xp"],
        "xp_progress": xp_progress,
        "xp_needed": xp_needed,
        "xp_pct": min(100, round(xp_progress / xp_needed * 100)),
        "stats": {
            "intelligence": intelligence,
            "defense": defense,
            "memory": memory,
            "constitution": constitution,
            "discipline": discipline,
        },
        "achievements_unlocked": state["achievements_unlocked"],
        "achievements_all": [a["id"] for a in ACHIEVEMENTS],
        "events_processed": state["events_processed"],
        "counters": counters,
    }
