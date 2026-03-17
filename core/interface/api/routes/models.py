"""Model listing endpoint — queries Ollama for available models."""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()


@router.get("/models")
def list_models():
    try:
        from ollama import Client
        client = Client(timeout=10)
        response = client.list()
        models = [
            {"name": m.model, "size": m.size, "modified_at": str(m.modified_at)}
            for m in response.models
        ]
    except Exception:
        models = []

    # Always include cloud model as option
    from core.interface.settings import get_setting
    cloud_model = get_setting("cloud_model")
    return {
        "local": models,
        "cloud": [{"name": cloud_model, "type": "cloud"}],
    }
