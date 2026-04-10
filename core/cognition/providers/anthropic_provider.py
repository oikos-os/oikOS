"""AnthropicProvider — Claude inference via the Anthropic Messages API."""

from __future__ import annotations

import logging
import os
import time
from typing import Iterator

from core.interface.models import CompletionResponse, ProviderMessage

log = logging.getLogger(__name__)


class AnthropicProvider:
    """Inference provider using the Anthropic Python SDK (native Messages API)."""

    provider_name = "anthropic"

    def __init__(
        self,
        default_model: str = "claude-sonnet-4-20250514",
        max_tokens: int = 4096,
        api_key: str | None = None,
    ):
        self._default_model = default_model
        self._default_max_tokens = max_tokens
        self._api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        self._client = None
        if self._api_key:
            import anthropic
            self._client = anthropic.Anthropic(api_key=self._api_key)

    def _extract_system(
        self, messages: list[ProviderMessage]
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
        temperature: float = 0.7,
        max_tokens: int = 2048,
        **kwargs,
    ) -> CompletionResponse:
        if not self._client:
            return CompletionResponse(
                text="[INFERENCE ERROR: ANTHROPIC_API_KEY not set]",
                model=model or self._default_model,
                provider=self.provider_name,
            )

        system, api_msgs = self._extract_system(messages)
        create_kwargs = {
            "model": model or self._default_model,
            "messages": api_msgs,
            "max_tokens": max_tokens or self._default_max_tokens,
            "temperature": temperature,
        }
        if system:
            create_kwargs["system"] = system

        try:
            t0 = time.monotonic()
            resp = self._client.messages.create(**create_kwargs)
            latency = int((time.monotonic() - t0) * 1000)

            text = "".join(
                block.text for block in resp.content if block.type == "text"
            )

            return CompletionResponse(
                text=text,
                model=resp.model,
                provider=self.provider_name,
                input_tokens=resp.usage.input_tokens,
                output_tokens=resp.usage.output_tokens,
                latency_ms=latency,
            )
        except Exception as e:
            log.error("AnthropicProvider.generate failed: %s", e)
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
        temperature: float = 0.7,
        max_tokens: int = 2048,
        **kwargs,
    ) -> Iterator[str]:
        if not self._client:
            return

        system, api_msgs = self._extract_system(messages)
        create_kwargs = {
            "model": model or self._default_model,
            "messages": api_msgs,
            "max_tokens": max_tokens or self._default_max_tokens,
            "temperature": temperature,
        }
        if system:
            create_kwargs["system"] = system

        try:
            with self._client.messages.stream(**create_kwargs) as stream:
                for event in stream:
                    if hasattr(event, "type") and event.type == "content_block_delta":
                        if hasattr(event.delta, "text"):
                            yield event.delta.text
        except Exception as e:
            log.error("AnthropicProvider.stream failed: %s", e)

    def count_tokens(self, text: str) -> int:
        return int(len(text.split()) * 1.3)

    def is_available(self) -> bool:
        return self._client is not None
