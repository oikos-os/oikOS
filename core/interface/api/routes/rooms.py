"""Room management endpoints — CRUD, switch, active."""
from __future__ import annotations

import logging
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

log = logging.getLogger(__name__)

router = APIRouter()


class RoomCreateRequest(BaseModel):
    id: str
    name: str
    description: str = ""
    template: str | None = None
    toolsets: list[str] | None = None
    vault_scope_mode: str = "all"
    vault_scope_paths: list[str] | None = None


class RoomUpdateRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    toolsets: list[str] | None = None
    vault_scope_mode: Literal["all", "include", "exclude"] | None = None
    vault_scope_paths: list[str] | None = None
    autonomy_overrides: dict[str, str] | None = None
    model_provider: str | None = None
    model_model: str | None = None


class RoomModelRequest(BaseModel):
    model: str


class RoomProvidersRequest(BaseModel):
    providers: list[str]


class RoomSwitchRequest(BaseModel):
    room_id: str


@router.get("")
def list_rooms():
    from core.rooms.manager import get_room_manager
    return [r.model_dump() for r in get_room_manager().list_rooms()]


@router.get("/active")
def active_room():
    from core.rooms.manager import get_room_manager
    return get_room_manager().get_active_room().model_dump()


@router.get("/{room_id}")
def get_room(room_id: str):
    from core.rooms.manager import get_room_manager
    try:
        return get_room_manager().get_room(room_id).model_dump()
    except ValueError:
        raise HTTPException(404, "Room not found")


@router.post("")
def create_room(req: RoomCreateRequest):
    from core.rooms.manager import get_room_manager
    from core.rooms.models import RoomConfig, RoomVaultScope

    if req.template:
        from core.rooms.defaults import TEMPLATES
        if req.template not in TEMPLATES:
            raise HTTPException(400, f"Unknown template: {req.template}")
        tpl = dict(TEMPLATES[req.template])
        tpl.update(id=req.id, name=req.name, description=req.description)
        config = RoomConfig.model_validate(tpl)
    else:
        vault_scope = RoomVaultScope(
            mode=req.vault_scope_mode,
            paths=req.vault_scope_paths or [],
        )
        config = RoomConfig(
            id=req.id, name=req.name, description=req.description,
            toolsets=req.toolsets, vault_scope=vault_scope,
        )

    try:
        return get_room_manager().create_room(config).model_dump()
    except ValueError:
        raise HTTPException(400, "Invalid room configuration")


@router.put("/{room_id}")
def update_room(room_id: str, req: RoomUpdateRequest):
    from core.rooms.manager import get_room_manager
    updates = {k: v for k, v in req.model_dump(exclude_unset=True).items()}
    # Expand nested fields into the structure RoomConfig expects
    if "vault_scope_mode" in updates or "vault_scope_paths" in updates:
        updates["vault_scope"] = {
            "mode": updates.pop("vault_scope_mode", "all"),
            "paths": updates.pop("vault_scope_paths", []),
        }
    if "autonomy_overrides" in updates:
        updates["autonomy"] = {"overrides": updates.pop("autonomy_overrides")}
    if "model_provider" in updates or "model_model" in updates:
        updates["model"] = {
            "provider": updates.pop("model_provider", None),
            "model": updates.pop("model_model", None),
        }
    try:
        return get_room_manager().update_room(room_id, updates).model_dump()
    except ValueError:
        raise HTTPException(400, "Invalid room configuration")


@router.delete("/{room_id}")
def delete_room(room_id: str):
    from core.rooms.manager import get_room_manager
    try:
        get_room_manager().delete_room(room_id)
        return {"status": "deleted"}
    except ValueError:
        raise HTTPException(400, "Cannot delete this room")


@router.put("/{room_id}/model")
def set_room_model(room_id: str, req: RoomModelRequest):
    """Set model default for a room. Accepts 'auto', provider prefix, or model name."""
    from core.rooms.manager import get_room_manager

    model_value = req.model.strip()
    if not model_value:
        raise HTTPException(400, "Model value cannot be empty")

    _KNOWN_PROVIDERS = {"ollama", "anthropic", "anthropic-oauth", "gemini", "openai", "litellm"}

    # "auto" resets to default behavior (no provider/model override)
    if model_value == "auto":
        provider, model_name = None, None
    elif ":" in model_value and model_value.split(":", 1)[0] in _KNOWN_PROVIDERS:
        # Provider prefix format: "ollama:qwen2.5:14b", "anthropic:", "gemini:"
        parts = model_value.split(":", 1)
        provider = parts[0]
        model_name = parts[1] if parts[1] else None
    else:
        # Plain model name — validate against available models
        provider = None
        model_name = model_value

        # Validate model exists in Ollama or matches a cloud model
        valid = False
        try:
            from ollama import Client
            client = Client(timeout=10)
            local_models = [m.model for m in client.list().models]
            if model_name in local_models:
                valid = True
        except Exception as e:
            log.debug("model validation ollama check suppressed: %s", e)
        if not valid:
            from core.interface.settings import get_setting
            cloud_model = get_setting("cloud_model")
            if model_name == cloud_model:
                valid = True
        if not valid:
            raise HTTPException(400, f"Unknown model: {model_name}")

    updates = {"model": {"provider": provider, "model": model_name}}
    try:
        room = get_room_manager().update_room(room_id, updates)
        return room.model_dump()
    except ValueError:
        raise HTTPException(404, "Room not found")


@router.put("/{room_id}/providers")
def set_room_providers(room_id: str, req: RoomProvidersRequest):
    """Set allowed inference providers for a room."""
    from core.rooms.manager import get_room_manager

    providers = req.providers
    if not providers:
        raise HTTPException(400, "Provider list cannot be empty — a Room needs at least one provider")

    # Validate against globally configured providers
    try:
        from core.cognition.providers.bootstrap import create_registry
        registry = create_registry()
        available = set(registry.list_all())
    except Exception:
        available = {"local"}

    unknown = set(providers) - available
    if unknown:
        raise HTTPException(400, f"Unknown providers: {sorted(unknown)}. Available: {sorted(available)}")

    updates = {"allowed_providers": providers}
    try:
        room = get_room_manager().update_room(room_id, updates)
        return room.model_dump()
    except ValueError:
        raise HTTPException(404, "Room not found")


@router.get("/{room_id}/usage")
def room_usage(room_id: str):
    from core.rooms.limits import get_room_usage
    return get_room_usage(room_id)


@router.post("/switch")
def switch_room(req: RoomSwitchRequest):
    from core.rooms.manager import get_room_manager
    try:
        room = get_room_manager().switch_room(req.room_id)
        return room.model_dump()
    except ValueError:
        raise HTTPException(400, "Room not found")
