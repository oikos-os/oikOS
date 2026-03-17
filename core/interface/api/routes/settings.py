"""Settings API — GET/PUT /api/settings."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter()


class SettingUpdate(BaseModel):
    key: str
    value: object


@router.get("")
def get_settings():
    from core.interface.settings import get_all_settings
    return get_all_settings()


@router.put("")
def put_setting(body: SettingUpdate):
    from core.interface.settings import update_setting
    try:
        update_setting(body.key, body.value)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"ok": True, "key": body.key, "value": body.value}
