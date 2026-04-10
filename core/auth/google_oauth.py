"""Google OAuth 2.0 — authorization flow, token exchange, refresh."""

from __future__ import annotations

import logging
import os
import secrets
import threading
import time
from dataclasses import dataclass
from urllib.parse import urlencode

import httpx

log = logging.getLogger(__name__)

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/drive.readonly",
    "openid",
    "email",
    "profile",
]

REDIRECT_URI = "http://localhost:8420/auth/google/callback"


@dataclass
class GoogleTokens:
    """In-memory Google OAuth token store."""

    access_token: str
    refresh_token: str | None
    expires_at: float  # Unix ms
    email: str
    scopes: list[str]

    def __repr__(self) -> str:
        return f"GoogleTokens(email={self.email!r}, access_token='[REDACTED]')"


# Module-level in-memory store (single user, single process)
_google_tokens: GoogleTokens | None = None
_csrf_state: str | None = None
_token_lock = threading.Lock()  # guards _google_tokens mutations


def get_client_credentials() -> tuple[str, str]:
    """Read GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET from env."""
    client_id = os.environ.get("GOOGLE_CLIENT_ID", "")
    client_secret = os.environ.get("GOOGLE_CLIENT_SECRET", "")
    return client_id, client_secret


def get_authorization_url() -> tuple[str, str]:
    """Build the Google OAuth consent URL. Returns (url, state)."""
    global _csrf_state
    client_id, _ = get_client_credentials()
    if not client_id:
        raise ValueError("GOOGLE_CLIENT_ID not set in environment")

    _csrf_state = secrets.token_urlsafe(32)
    params = {
        "client_id": client_id,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "scope": " ".join(SCOPES),
        "access_type": "offline",
        "prompt": "consent",
        "state": _csrf_state,
    }
    return f"{GOOGLE_AUTH_URL}?{urlencode(params)}", _csrf_state


def verify_state(state: str) -> bool:
    """Verify and consume the CSRF state parameter (one-time use)."""
    global _csrf_state
    if _csrf_state is not None and state == _csrf_state:
        _csrf_state = None
        return True
    return False


def exchange_code(code: str) -> GoogleTokens | None:
    """Exchange authorization code for tokens + fetch user email."""
    global _google_tokens
    client_id, client_secret = get_client_credentials()

    with httpx.Client(timeout=10.0) as client:
        try:
            resp = client.post(
                GOOGLE_TOKEN_URL,
                data={
                    "code": code,
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "redirect_uri": REDIRECT_URI,
                    "grant_type": "authorization_code",
                },
            )
            if resp.status_code != 200:
                log.error("Google token exchange failed: HTTP %d", resp.status_code)
                return None

            data = resp.json()
            access_token = data.get("access_token")
            if not access_token:
                log.error("Google token exchange: no access_token in response")
                return None

            expires_in = max(data.get("expires_in", 3600), 60)

            # Fetch user email from userinfo endpoint
            email = ""
            try:
                info_resp = client.get(
                    GOOGLE_USERINFO_URL,
                    headers={"Authorization": f"Bearer {access_token}"},
                )
                if info_resp.status_code == 200:
                    email = info_resp.json().get("email", "")
            except Exception as e:
                log.warning("Google userinfo fetch failed: %s", e)

            tokens = GoogleTokens(
                access_token=access_token,
                refresh_token=data.get("refresh_token"),
                expires_at=int((time.time() + expires_in) * 1000),
                email=email,
                scopes=data.get("scope", "").split(),
            )
            with _token_lock:
                _google_tokens = tokens
            log.info("Google OAuth connected: %s", email)
            return tokens

        except httpx.HTTPError as e:
            log.error("Google token exchange error: %s", e)
            return None


def refresh_google_token() -> bool:
    """Refresh the Google access token using the stored refresh token.

    Thread-safe: acquires _token_lock before mutating _google_tokens.
    """
    global _google_tokens
    with _token_lock:
        if not _google_tokens or not _google_tokens.refresh_token:
            return False
        refresh_tok = _google_tokens.refresh_token

    client_id, client_secret = get_client_credentials()

    with httpx.Client(timeout=10.0) as client:
        try:
            resp = client.post(
                GOOGLE_TOKEN_URL,
                data={
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "refresh_token": refresh_tok,
                    "grant_type": "refresh_token",
                },
            )
            if resp.status_code == 200:
                data = resp.json()
                access_token = data.get("access_token")
                if access_token:
                    expires_in = max(data.get("expires_in", 3600), 60)
                    with _token_lock:
                        if _google_tokens is not None:
                            _google_tokens.access_token = access_token
                            _google_tokens.expires_at = int((time.time() + expires_in) * 1000)
                    log.info("Google token refreshed")
                    return True
            log.warning("Google token refresh failed: HTTP %d", resp.status_code)
            return False
        except httpx.HTTPError as e:
            log.warning("Google token refresh error: %s", e)
            return False


def get_google_tokens() -> GoogleTokens | None:
    """Get current Google tokens, refreshing if near expiry."""
    with _token_lock:
        tokens = _google_tokens
    if tokens is None:
        return None

    now_ms = time.time() * 1000
    if tokens.expires_at - now_ms < 300_000:  # 5 min threshold
        refresh_google_token()

    with _token_lock:
        return _google_tokens


def disconnect_google() -> None:
    """Clear stored Google tokens."""
    global _google_tokens, _csrf_state
    with _token_lock:
        _google_tokens = None
    _csrf_state = None
    log.info("Google OAuth disconnected")


def is_google_connected() -> bool:
    """Check if Google OAuth tokens are available."""
    return _google_tokens is not None


def get_google_status() -> dict:
    """Public accessor for Google connection status (safe fields only)."""
    if _google_tokens is None:
        return {"connected": False}
    return {
        "connected": True,
        "email": _google_tokens.email,
        "scopes": _google_tokens.scopes,
    }
