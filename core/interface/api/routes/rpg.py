"""RPG overlay endpoints — stats, XP grant, achievements."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()


class XPEventRequest(BaseModel):
    event_type: str


class AchievementRequest(BaseModel):
    achievement_id: str


@router.get("/rpg/stats")
def rpg_stats():
    from core.agency.rpg import calculate_stats

    return calculate_stats()


@router.post("/rpg/xp")
def rpg_grant_xp(req: XPEventRequest):
    from core.agency.rpg import grant_xp, XP_REWARDS

    if req.event_type not in XP_REWARDS:
        return {"error": f"Unknown event type: {req.event_type}", "granted": 0}

    state = grant_xp(req.event_type)
    return {
        "granted": XP_REWARDS[req.event_type],
        "total_xp": state["total_xp"],
        "level": state["level"],
    }


@router.post("/rpg/achievement")
def rpg_unlock_achievement(req: AchievementRequest):
    from core.agency.rpg import unlock_achievement

    state = unlock_achievement(req.achievement_id)
    return {"unlocked": state["achievements_unlocked"]}
