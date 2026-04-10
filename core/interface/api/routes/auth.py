"""OAuth API routes — /api/auth/*."""

from __future__ import annotations

import logging
import time

from fastapi import APIRouter, HTTPException

log = logging.getLogger(__name__)

router = APIRouter()


@router.get("/claude/discover")
async def claude_discover():
    """Check if Claude Code credentials exist on this machine."""
    from core.auth.claude_discovery import discover_claude_credentials

    creds = discover_claude_credentials()
    if creds:
        now_ms = time.time() * 1000
        return {
            "found": True,
            "subscription_type": creds.subscription_type,
            "source": "claude-code",
            "expired": creds.expires_at < now_ms,
        }
    return {"found": False}


@router.post("/claude/connect")
async def claude_connect():
    """Activate Claude Code credentials as the cloud inference provider."""
    from core.auth.claude_discovery import discover_claude_credentials
    from core.auth.claude_provider import AnthropicOAuthProvider
    from core.cognition.pipeline.dispatch import get_provider_registry

    creds = discover_claude_credentials()
    if not creds:
        raise HTTPException(status_code=404, detail="No Claude Code credentials found")

    provider = AnthropicOAuthProvider(creds)
    if not provider.is_available():
        raise HTTPException(status_code=422, detail="Token expired — re-authenticate in Claude Code")

    registry = get_provider_registry()
    registry.register("anthropic-oauth", provider)
    registry.set_default("anthropic-oauth")

    log.info("Claude Code OAuth connected (%s)", creds.subscription_type)
    return {
        "connected": True,
        "subscription_type": creds.subscription_type,
        "provider_name": "anthropic-oauth",
    }


@router.get("/claude/status")
async def claude_status():
    """Current Claude OAuth connection status."""
    from core.auth.claude_discovery import discover_claude_credentials
    from core.cognition.pipeline.dispatch import get_provider_registry

    registry = get_provider_registry()
    is_registered = "anthropic-oauth" in registry.list_all()

    if is_registered:
        try:
            provider = registry.get("anthropic-oauth")
            return {
                "connected": True,
                "subscription_type": getattr(provider, "subscription_type", "unknown"),
                "provider_name": "anthropic-oauth",
                "available": provider.is_available(),
                "credentials_available": True,
            }
        except Exception as exc:
            log.warning("claude_status registry error: %s", exc)

    creds = discover_claude_credentials()
    result = {"connected": False, "credentials_available": creds is not None}
    if creds:
        result["subscription_type"] = creds.subscription_type
    return result


@router.post("/claude/disconnect")
async def claude_disconnect():
    """Revert to local provider as default."""
    from core.cognition.pipeline.dispatch import get_provider_registry

    registry = get_provider_registry()
    if registry.get_default_name() == "anthropic-oauth":
        registry.set_default("local")
        log.info("Claude Code OAuth disconnected — reverted to local")

    return {"disconnected": True}


# ── Google OAuth ────────────────────────────────────────────────────


@router.get("/google/connect")
async def google_connect():
    """Redirect to Google OAuth consent screen."""
    from starlette.responses import RedirectResponse

    from core.auth.google_oauth import get_authorization_url

    try:
        url, _state = get_authorization_url()
    except ValueError:
        raise HTTPException(status_code=500, detail="OAuth configuration unavailable")

    return RedirectResponse(url=url, status_code=302)


@router.get("/google/status")
async def google_status():
    """Current Google OAuth connection status."""
    from core.auth.google_oauth import get_google_status

    return get_google_status()


@router.post("/google/disconnect")
async def google_disconnect():
    """Clear Google OAuth tokens."""
    from core.auth.google_oauth import disconnect_google

    disconnect_google()
    return {"disconnected": True}
