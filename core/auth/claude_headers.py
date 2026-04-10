"""Claude Code identity headers — match Claude Code's request fingerprint."""

from __future__ import annotations

import logging
from pathlib import Path

log = logging.getLogger(__name__)

_TOML_PATH = Path(__file__).parent / "config" / "auth_headers.toml"

CC_VERSION = "2.1.81"

_DEFAULTS: dict[str, str] = {
    "anthropic-beta": "claude-code-20250219,oauth-2025-04-20,interleaved-thinking-2025-05-14",
    "anthropic-version": "2023-06-01",
    "user-agent": f"claude-code/{CC_VERSION} (external, cli)",
}


def load_claude_headers() -> dict[str, str]:
    """Load identity headers from TOML config, fall back to defaults."""
    try:
        import tomllib

        if _TOML_PATH.exists():
            data = tomllib.loads(_TOML_PATH.read_text(encoding="utf-8"))
            return dict(data.get("headers", _DEFAULTS))
    except Exception as e:
        log.debug("Failed to load auth_headers.toml: %s", e)
    return dict(_DEFAULTS)


def get_claude_code_headers(access_token: str) -> dict[str, str]:
    """Return complete headers for an Anthropic API request matching Claude Code."""
    headers = load_claude_headers()
    headers["Authorization"] = f"Bearer {access_token}"
    headers["Content-Type"] = "application/json"
    return headers
