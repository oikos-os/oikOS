"""Onboarding endpoints — PUBLIC (no auth required for new users).

All mutating endpoints check is_onboarding_complete() and return 403 if
setup is already done. This prevents unauthenticated callers from modifying
identity, providers, or settings after the initial setup.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter()


def _require_not_complete() -> None:
    """Block mutating onboarding calls after setup is done."""
    from core.onboarding.state import is_onboarding_complete
    if is_onboarding_complete():
        raise HTTPException(403, "Onboarding already complete")


class IdentityRequest(BaseModel):
    name: str
    description: str = ""


class ModelRequest(BaseModel):
    provider: str
    model: str


class ProviderTestRequest(BaseModel):
    provider: str
    api_key: str


class RoomRequest(BaseModel):
    template: str


@router.get("/status")
def onboarding_status():
    from core.onboarding.state import is_onboarding_complete, get_step
    return {"complete": is_onboarding_complete(), "step": get_step()}


@router.get("/detect-backends")
async def detect_backends_endpoint():
    from core.onboarding.detector import BackendDetector
    return await BackendDetector().scan()


@router.post("/identity")
def save_identity(req: IdentityRequest):
    _require_not_complete()
    from core.onboarding.identity import bootstrap_identity
    from core.onboarding.state import set_step
    try:
        created = bootstrap_identity(req.name, req.description)
        set_step(1)
        return {"created": created}
    except ValueError:
        raise HTTPException(400, "Invalid identity configuration")


@router.post("/model")
def save_model(req: ModelRequest):
    _require_not_complete()
    from core.onboarding.manager import save_model_selection
    from core.onboarding.state import set_step
    save_model_selection(req.provider, req.model)
    set_step(2)
    return {"provider": req.provider, "model": req.model}


@router.post("/providers")
def save_provider(req: ProviderTestRequest):
    _require_not_complete()
    from core.onboarding.manager import save_provider_key
    from core.onboarding.state import set_step
    try:
        save_provider_key(req.provider, req.api_key)
        set_step(3)
        return {"saved": req.provider}
    except ValueError:
        raise HTTPException(400, "Unknown provider")


@router.post("/providers/test")
def test_provider(req: ProviderTestRequest):
    from core.onboarding.manager import test_provider_connection
    result = test_provider_connection(req.provider, req.api_key)
    if not result["success"]:
        raise HTTPException(400, result["message"])
    return result


@router.post("/rooms")
def create_onboarding_room(req: RoomRequest):
    _require_not_complete()
    from core.rooms.manager import get_room_manager
    from core.rooms.defaults import TEMPLATES
    from core.rooms.models import RoomConfig
    from core.onboarding.state import set_step
    if req.template not in TEMPLATES:
        raise HTTPException(400, "Unknown template")
    tpl = dict(TEMPLATES[req.template])
    tpl["id"] = req.template
    tpl["name"] = req.template.title()
    config = RoomConfig.model_validate(tpl)
    try:
        get_room_manager().create_room(config)
    except ValueError:
        pass  # Room may already exist
    set_step(4)
    return {"room": req.template}


@router.post("/complete")
def complete_onboarding():
    _require_not_complete()
    from core.onboarding.state import mark_onboarding_complete
    from core.onboarding.manager import write_providers_toml
    from core.onboarding.detector import detect_backends
    detected = detect_backends()
    write_providers_toml(detected_backends=detected)
    mark_onboarding_complete()
    return {"complete": True}
