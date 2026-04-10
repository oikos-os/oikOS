"""Token refresh for Claude Code OAuth credentials."""

from __future__ import annotations

import logging
import time

import httpx

from core.auth.claude_discovery import RefreshedToken

log = logging.getLogger(__name__)

# Fallback defaults — source of truth is core/auth/config/auth_headers.toml [oauth]
_DEFAULT_CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"
_DEFAULT_TOKEN_URL = "https://api.anthropic.com/v1/oauth/token"


def _load_oauth_config() -> tuple[str, str]:
    """Load client_id and token_url from auth_headers.toml, with defaults."""
    try:
        import tomllib
        from pathlib import Path

        toml_path = Path(__file__).parent / "config" / "auth_headers.toml"
        if toml_path.exists():
            data = tomllib.loads(toml_path.read_text(encoding="utf-8"))
            oauth = data.get("oauth", {})
            return (
                oauth.get("client-id", _DEFAULT_CLIENT_ID),
                oauth.get("token-url", _DEFAULT_TOKEN_URL),
            )
    except Exception as e:
        log.debug("Failed to load oauth config from TOML: %s", e)
    return _DEFAULT_CLIENT_ID, _DEFAULT_TOKEN_URL


def refresh_access_token(refresh_token: str) -> RefreshedToken | None:
    """Exchange a refresh token for a new access token."""
    client_id, token_url = _load_oauth_config()

    with httpx.Client(timeout=10.0) as client:
        try:
            response = client.post(
                token_url,
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                    "client_id": client_id,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            if response.status_code == 200:
                data = response.json()
                access_token = data.get("access_token")
                if not access_token:
                    log.warning("Token refresh: missing access_token in response")
                    return None
                expires_in = max(data.get("expires_in", 28800), 60)
                return RefreshedToken(
                    access_token=access_token,
                    expires_at=int((time.time() + expires_in) * 1000),
                )
            log.warning("Token refresh failed: HTTP %d", response.status_code)
            return None
        except httpx.HTTPError as e:
            log.warning("Token refresh error: %s", e)
            return None
