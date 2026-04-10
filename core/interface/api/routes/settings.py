"""Settings API — GET/PUT /api/settings."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

log = logging.getLogger(__name__)

router = APIRouter()


class SettingUpdate(BaseModel):
    key: str
    value: object


@router.get("")
def get_settings():
    from core.interface.settings import get_tiered_settings
    return get_tiered_settings()


@router.put("")
def put_setting(body: SettingUpdate):
    from core.interface.settings import update_setting
    try:
        result = update_setting(body.key, body.value)
    except KeyError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except ValueError as e:
        log.warning("[put_setting] invalid setting: %s", e)
        raise HTTPException(status_code=400, detail=str(e))
    return result
