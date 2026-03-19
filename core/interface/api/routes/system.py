"""System endpoints — state, health, credits, config."""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()


@router.get("/state")
def get_state():
    from core.autonomic.fsm import get_current_state, get_last_transition_time
    from core.interface.api.server import get_uptime
    from core.interface.config import API_VERSION, INFERENCE_MODEL

    result = {
        "product": "oikOS",
        "fsm_state": get_current_state().value,
        "model": INFERENCE_MODEL,
        "version": API_VERSION,
        "uptime": round(get_uptime(), 1),
        "last_transition": get_last_transition_time(),
    }

    try:
        from core.rooms.manager import get_room_manager
        active = get_room_manager().get_active_room()
        result["active_room"] = {"id": active.id, "name": active.name}
    except Exception:
        result["active_room"] = None

    return result


@router.get("/health")
def get_health():
    from core.autonomic.daemon import get_status
    from core.memory.embedder import check_health

    status = get_status()
    return {
        "running": status["running"],
        "daemon": status,
        "ollama_embed": check_health(),
    }


@router.get("/credits")
def get_credits():
    from core.safety.credits import load_credits

    bal = load_credits()
    return bal.model_dump()


@router.get("/config")
def get_config():
    from core.interface.config import (
        API_VERSION,
        CLOUD_MODEL,
        CLOUD_ROUTING_POSTURE,
        CREDITS_MONTHLY_CAP,
        DEFAULT_TOKEN_BUDGET,
        INFERENCE_MODEL,
        ROUTING_CONFIDENCE_THRESHOLD,
    )

    return {
        "product": "oikOS",
        "version": API_VERSION,
        "inference_model": INFERENCE_MODEL,
        "cloud_model": CLOUD_MODEL,
        "token_budget": DEFAULT_TOKEN_BUDGET,
        "monthly_cap": CREDITS_MONTHLY_CAP,
        "confidence_threshold": ROUTING_CONFIDENCE_THRESHOLD,
        "cloud_posture": CLOUD_ROUTING_POSTURE,
    }
