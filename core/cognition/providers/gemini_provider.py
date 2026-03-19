"""GeminiProvider — wraps existing cloud.py as a Protocol-compliant provider."""

from __future__ import annotations

import logging
import os
from typing import Iterator

from core.cognition.cloud import send_to_cloud, stream_cloud
from core.interface.models import CompletionResponse, ProviderMessage

log = logging.getLogger(__name__)


class GeminiProvider:
    """Inference provider wrapping existing Google Gemini cloud bridge."""

    provider_name = "gemini"

    def __init__(self, default_model: str = "gemini-2.5-pro"):
        self._default_model = default_model
        self._has_key = bool(os.environ.get("GEMINI_API_KEY"))

    def _split_messages(
        self, messages: list[ProviderMessage]
    ) -> tuple[str, str, str]:
        """Extract (query, context, system) from message list.

        Last user message = query. Prior non-system messages = context.
        System message = system prompt.
        """
        system = ""
        context_parts = []

        for m in messages:
            if m.role == "system":
                system = m.content

        non_system = [m for m in messages if m.role != "system"]
        query = non_system[-1].content if non_system else ""
        for m in non_system[:-1]:
            prefix = "User" if m.role == "user" else "Assistant"
            context_parts.append(f"{prefix}: {m.content}")

        context = "\n".join(context_parts)
        return query, context, system

    def generate(
        self,
        messages: list[ProviderMessage],
        *,
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        **kwargs,
    ) -> CompletionResponse:
        query, context, system = self._split_messages(messages)

        try:
            cloud_resp = send_to_cloud(
                query, context, system=system,
                model=model or self._default_model,
            )
            return CompletionResponse(
                text=cloud_resp.text,
                model=cloud_resp.model,
                provider=self.provider_name,
                input_tokens=cloud_resp.input_tokens,
                output_tokens=cloud_resp.output_tokens,
                latency_ms=cloud_resp.latency_ms,
            )
        except Exception as e:
            log.error("GeminiProvider.generate failed: %s", e)
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
        query, context, system = self._split_messages(messages)

        try:
            yield from stream_cloud(
                query, context, system=system,
                model=model or self._default_model,
            )
        except Exception as e:
            log.error("GeminiProvider.stream failed: %s", e)

    def count_tokens(self, text: str) -> int:
        return int(len(text.split()) * 1.3)

    def is_available(self) -> bool:
        return self._has_key
