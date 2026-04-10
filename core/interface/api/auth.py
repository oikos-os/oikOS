"""API key authentication — reads OIKOS_API_KEY from env. Skips if unset."""

from __future__ import annotations

import os

from fastapi import HTTPException, Security
from fastapi.security import APIKeyHeader

_header_scheme = APIKeyHeader(name="X-API-Key", auto_error=False)


def get_api_key(api_key: str | None = Security(_header_scheme)) -> str | None:
    """FastAPI dependency — validates API key if OIKOS_API_KEY is set."""
    expected = os.environ.get("OIKOS_API_KEY")
    if not expected:
        return None  # no auth configured
    if not api_key or api_key != expected:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")
    return api_key


def validate_ws_token(token: str | None) -> bool:
    """Validate WebSocket ?token= query param. Returns True if valid or auth disabled."""
    expected = os.environ.get("OIKOS_API_KEY")
    if not expected:
        return True
    return token == expected
