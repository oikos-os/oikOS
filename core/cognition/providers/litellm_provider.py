"""LiteLLMProvider — optional wrapper for 100+ cloud providers via litellm.

Install: pip install oikos[cloud]
Gracefully degrades if litellm is not installed.
"""

from __future__ import annotations

import logging
import time
from typing import Iterator

from core.interface.models import CompletionResponse, ProviderMessage

log = logging.getLogger(__name__)


class LiteLLMProvider:
    """Inference provider using LiteLLM for multi-provider cloud access."""

    provider_name = "litellm"

    def __init__(self, default_model: str = "gpt-4o"):
        self._default_model = default_model
        try:
            import litellm
            self._litellm = litellm
        except ImportError:
            self._litellm = None

    def generate(
        self,
        messages: list[ProviderMessage],
        *,
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        **kwargs,
    ) -> CompletionResponse:
        if not self._litellm:
            return CompletionResponse(
                text="[INFERENCE ERROR: litellm not installed. Run: pip install litellm]",
                model=model or self._default_model,
                provider=self.provider_name,
            )

        api_msgs = [{"role": m.role, "content": m.content} for m in messages]
        try:
            t0 = time.monotonic()
            resp = self._litellm.completion(
                model=model or self._default_model,
                messages=api_msgs,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            latency = int((time.monotonic() - t0) * 1000)

            return CompletionResponse(
                text=resp.choices[0].message.content,
                model=resp.model,
                provider=self.provider_name,
                input_tokens=resp.usage.prompt_tokens,
                output_tokens=resp.usage.completion_tokens,
                latency_ms=latency,
            )
        except Exception as e:
            log.error("LiteLLMProvider.generate failed: %s", e)
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
        if not self._litellm:
            return

        api_msgs = [{"role": m.role, "content": m.content} for m in messages]
        try:
            resp = self._litellm.completion(
                model=model or self._default_model,
                messages=api_msgs,
                temperature=temperature,
                max_tokens=max_tokens,
                stream=True,
            )
            for chunk in resp:
                delta = chunk.choices[0].delta
                if hasattr(delta, "content") and delta.content:
                    yield delta.content
        except Exception as e:
            log.error("LiteLLMProvider.stream failed: %s", e)

    def count_tokens(self, text: str) -> int:
        return int(len(text.split()) * 1.3)

    def is_available(self) -> bool:
        return self._litellm is not None
