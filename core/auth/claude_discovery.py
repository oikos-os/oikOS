"""Claude Code credential discovery — read locally stored OAuth tokens."""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)


@dataclass
class ClaudeCredentials:
    """Normalized Claude Code OAuth credentials."""

    access_token: str
    refresh_token: str
    expires_at: float  # Unix timestamp in milliseconds
    scopes: list[str]
    subscription_type: str  # "max", "pro", or "unknown"
    source_path: str

    def __repr__(self) -> str:
        return (
            f"ClaudeCredentials(subscription_type={self.subscription_type!r}, "
            f"source_path={self.source_path!r}, access_token='[REDACTED]', "
            f"refresh_token='[REDACTED]')"
        )


@dataclass
class RefreshedToken:
    """Result of a token refresh — only new token + expiry."""

    access_token: str
    expires_at: float  # Unix ms

    def __repr__(self) -> str:
        return f"RefreshedToken(access_token='[REDACTED]', expires_at={self.expires_at})"


def _get_credential_paths() -> list[Path]:
    """Return possible Claude Code credential file locations."""
    paths = []
    home = Path.home()

    # Format A: dot-prefixed hidden file (actual, found on SIGMA-01)
    paths.append(home / ".claude" / ".credentials.json")

    # Windows alternate
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA", "")
        if appdata:
            paths.append(Path(appdata) / "Claude" / "credentials.json")

    # Format B fallback (cross-platform)
    paths.append(home / ".claude" / "credentials.json")

    return paths


def _parse_format_a(data: dict, path: str) -> ClaudeCredentials | None:
    """Parse Format A: nested claudeAiOauth key, camelCase fields."""
    oauth = data.get("claudeAiOauth")
    if not oauth or not isinstance(oauth, dict):
        return None

    access = oauth.get("accessToken", "")
    refresh = oauth.get("refreshToken", "")

    if not access.startswith("sk-ant-oat") or not refresh.startswith("sk-ant-ort"):
        return None

    return ClaudeCredentials(
        access_token=access,
        refresh_token=refresh,
        expires_at=oauth.get("expiresAt", 0),
        scopes=oauth.get("scopes", []),
        subscription_type=oauth.get("subscriptionType", "unknown"),
        source_path=path,
    )


def _parse_format_b(data: dict, path: str) -> ClaudeCredentials | None:
    """Parse Format B: flat structure, snake_case fields (brief fallback)."""
    access = data.get("access_token", "")
    refresh = data.get("refresh_token", "")

    if not access.startswith("sk-ant-oat") or not refresh.startswith("sk-ant-ort"):
        return None

    expires_in = max(data.get("expires_in", 28800), 60)
    scope_str = data.get("scope", "")
    scopes = scope_str.split() if isinstance(scope_str, str) else []

    return ClaudeCredentials(
        access_token=access,
        refresh_token=refresh,
        expires_at=int((time.time() + expires_in) * 1000),
        scopes=scopes,
        subscription_type="unknown",
        source_path=path,
    )


def discover_claude_credentials() -> ClaudeCredentials | None:
    """Scan for Claude Code credentials. Returns normalized creds or None."""
    for path in _get_credential_paths():
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, PermissionError, OSError):
            continue

        creds = _parse_format_a(data, str(path))
        if creds:
            log.info("Claude Code credentials found: %s (%s)", path, creds.subscription_type)
            return creds

        creds = _parse_format_b(data, str(path))
        if creds:
            log.info("Claude Code credentials found (format B): %s", path)
            return creds

    return None
