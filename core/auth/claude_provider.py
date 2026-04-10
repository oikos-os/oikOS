"""AnthropicOAuthProvider — Claude inference via OAuth tokens from Claude Code."""

from __future__ import annotations

import json
import logging
import time
from typing import Iterator

import httpx

from core.auth.claude_discovery import ClaudeCredentials
from core.auth.claude_headers import CC_VERSION as _CC_VERSION
from core.auth.refresh import refresh_access_token
from core.interface.models import CompletionResponse, ProviderMessage

log = logging.getLogger(__name__)

_API_URL = "https://api.anthropic.com/v1/messages?beta=true"
_REFRESH_THRESHOLD_MS = 300_000  # 5 minutes
_MIN_THINKING_BUDGET = 1024

# Minimum headers required for OAuth inference on all Claude models
_REQUIRED_BETAS = (
    "claude-code-20250219,"
    "oauth-2025-04-20,"
    "interleaved-thinking-2025-05-14"
)


def _build_oauth_headers(access_token: str) -> dict[str, str]:
    """Build the minimum headers required for OAuth inference."""
    return {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "anthropic-version": "2023-06-01",
        "anthropic-beta": _REQUIRED_BETAS,
        "user-agent": f"claude-code/{_CC_VERSION} (external, cli)",
    }


def _build_system(user_system: str | None) -> list[dict]:
    """Build system blocks: billing header first, then user system prompt if any."""
    blocks = [{"type": "text", "text": f"x-anthropic-billing-header: cc_version={_CC_VERSION}; cc_entrypoint=cli;"}]
    if user_system:
        blocks.append({"type": "text", "text": user_system})
    return blocks


def _build_body(
    model: str, api_msgs: list[dict], max_tokens: int,
    system: str | None, *, stream: bool = False,
) -> dict:
    """Build request body with required OAuth fields (thinking + billing)."""
    body: dict = {
        "model": model,
        "messages": api_msgs,
        "max_tokens": max_tokens,
        "system": _build_system(system),
        "thinking": {
            "type": "enabled",
            "budget_tokens": max(_MIN_THINKING_BUDGET, max_tokens - 1),
        },
    }
    if stream:
        body["stream"] = True
    return body


class AnthropicOAuthProvider:
    """Inference provider using Claude Code's OAuth credentials."""

    provider_name = "anthropic-oauth"

    def __init__(
        self,
        credentials: ClaudeCredentials,
        default_model: str = "claude-sonnet-4-20250514",
        max_tokens: int = 4096,
    ):
        self._credentials = credentials
        self._default_model = default_model
        self._default_max_tokens = max_tokens
        self._client = httpx.Client(timeout=120.0)

    def close(self) -> None:
        self._client.close()

    def __del__(self) -> None:
        try:
            self._client.close()
        except Exception as e:
            log.debug("__del__ client close suppressed: %s", e)

    def _maybe_refresh(self) -> None:
        """Refresh the access token if within 5 minutes of expiry."""
        now_ms = time.time() * 1000
        if self._credentials.expires_at - now_ms < _REFRESH_THRESHOLD_MS:
            log.info("OAuth token near expiry, refreshing...")
            result = refresh_access_token(self._credentials.refresh_token)
            if result:
                self._credentials.access_token = result.access_token
                self._credentials.expires_at = result.expires_at
                log.info("OAuth token refreshed successfully")
            else:
                log.warning("OAuth token refresh failed — continuing with current token")

    @staticmethod
    def _extract_system(
        messages: list[ProviderMessage],
    ) -> tuple[str | None, list[dict]]:
        """Separate system prompt from messages (Anthropic API requirement)."""
        system = None
        api_msgs = []
        for m in messages:
            if m.role == "system":
                system = m.content
            else:
                api_msgs.append({"role": m.role, "content": m.content})
        return system, api_msgs

    def generate(
        self,
        messages: list[ProviderMessage],
        *,
        model: str | None = None,
        temperature: float = 0.7,  # ignored — thinking mode requires temperature=1
        max_tokens: int = 2048,
        **kwargs,
    ) -> CompletionResponse:
        self._maybe_refresh()
        headers = _build_oauth_headers(self._credentials.access_token)
        system, api_msgs = self._extract_system(messages)
        body = _build_body(
            model or self._default_model, api_msgs,
            max_tokens or self._default_max_tokens, system,
        )

        try:
            t0 = time.monotonic()
            resp = self._client.post(_API_URL, headers=headers, content=json.dumps(body))
            latency = int((time.monotonic() - t0) * 1000)

            if resp.status_code != 200:
                log.error("AnthropicOAuth generate: HTTP %d", resp.status_code)
                return CompletionResponse(
                    text=f"[INFERENCE ERROR: HTTP {resp.status_code}]",
                    model=model or self._default_model,
                    provider=self.provider_name,
                )

            data = resp.json()
            text = "".join(
                block["text"] for block in data.get("content", []) if block.get("type") == "text"
            )
            usage = data.get("usage", {})

            return CompletionResponse(
                text=text,
                model=data.get("model", model or self._default_model),
                provider=self.provider_name,
                input_tokens=usage.get("input_tokens", 0),
                output_tokens=usage.get("output_tokens", 0),
                latency_ms=latency,
            )
        except Exception as e:
            log.error("AnthropicOAuth generate error: %s", e)
            return CompletionResponse(
                text="[INFERENCE ERROR: provider unavailable]",
                model=model or self._default_model,
                provider=self.provider_name,
            )

    def stream(
        self,
        messages: list[ProviderMessage],
        *,
        model: str | None = None,
        temperature: float = 0.7,  # ignored — thinking mode requires temperature=1
        max_tokens: int = 2048,
        **kwargs,
    ) -> Iterator[str]:
        self._maybe_refresh()
        headers = _build_oauth_headers(self._credentials.access_token)
        system, api_msgs = self._extract_system(messages)
        body = _build_body(
            model or self._default_model, api_msgs,
            max_tokens or self._default_max_tokens, system, stream=True,
        )

        try:
            with self._client.stream("POST", _API_URL, headers=headers, content=json.dumps(body)) as resp:
                for line in resp.iter_lines():
                    if line.startswith("data: "):
                        chunk = line[6:]
                        if chunk == "[DONE]":
                            break
                        try:
                            event = json.loads(chunk)
                            if event.get("type") == "content_block_delta":
                                delta = event.get("delta", {})
                                if delta.get("type") == "text_delta":
                                    yield delta.get("text", "")
                        except json.JSONDecodeError:
                            continue
        except Exception as e:
            log.error("AnthropicOAuth stream error: %s", e)

    def count_tokens(self, text: str) -> int:
        return int(len(text.split()) * 1.3)

    @property
    def subscription_type(self) -> str:
        """Public accessor for the subscription type (e.g., 'max_5x')."""
        return self._credentials.subscription_type

    def is_available(self) -> bool:
        now_ms = time.time() * 1000
        return self._credentials.expires_at > now_ms
