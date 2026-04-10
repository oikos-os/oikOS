"""Model listing endpoint — queries Ollama for available models."""

from __future__ import annotations

import logging

from fastapi import APIRouter

log = logging.getLogger(__name__)

router = APIRouter()


@router.get("/models")
def list_models():
    # Get active room's allowed providers (None = all allowed)
    allowed_providers = None
    try:
        from core.rooms.manager import get_room_manager
        room = get_room_manager().get_active_room()
        allowed_providers = room.allowed_providers
    except Exception as e:
        log.debug("room allowed_providers lookup suppressed: %s", e)

    def _provider_allowed(provider: str) -> bool:
        return allowed_providers is None or provider in allowed_providers

    # Local models (provider = "ollama" / "local")
    models = []
    if _provider_allowed("local") or _provider_allowed("ollama"):
        try:
            from ollama import Client
            client = Client(timeout=10)
            response = client.list()
            models = [
                {"name": m.model, "size": m.size, "modified_at": str(m.modified_at)}
                for m in response.models
            ]
        except Exception as e:
            log.debug("ollama model listing suppressed: %s", e)

    # Cloud providers — include only if allowed
    cloud_models = []
    if _provider_allowed("gemini"):
        from core.interface.settings import get_setting
        cloud_model = get_setting("cloud_model")
        cloud_models.append({"name": cloud_model, "type": "cloud", "provider": "gemini"})

    if _provider_allowed("anthropic-oauth"):
        try:
            from core.cognition.providers.bootstrap import create_registry
            reg = create_registry()
            if "anthropic-oauth" in reg.list_all():
                p = reg.get("anthropic-oauth")
                if p.is_available():
                    cloud_models.append({"name": "claude-sonnet-4-20250514", "type": "cloud", "provider": "anthropic-oauth"})
                    cloud_models.append({"name": "claude-opus-4-6", "type": "cloud", "provider": "anthropic-oauth"})
                    cloud_models.append({"name": "claude-haiku-4-5-20251001", "type": "cloud", "provider": "anthropic-oauth"})
        except Exception as e:
            log.debug("anthropic-oauth model listing suppressed: %s", e)

    return {
        "local": models,
        "cloud": cloud_models,
    }
