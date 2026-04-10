"""oikOS auth — credential discovery and OAuth providers."""

from core.auth.claude_discovery import ClaudeCredentials, discover_claude_credentials
from core.auth.claude_provider import AnthropicOAuthProvider

__all__ = [
    "ClaudeCredentials",
    "discover_claude_credentials",
    "AnthropicOAuthProvider",
]
