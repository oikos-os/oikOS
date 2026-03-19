"""Room management endpoints — CRUD, switch, active."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

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
