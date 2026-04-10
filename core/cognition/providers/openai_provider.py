"""OpenAIProvider — dedicated first-class provider using httpx (not SDK).

Per SYNTH ruling T-047 #5: "Build a first-class OpenAIProvider alongside
Ollama, Anthropic, and Gemini. The OpenAIProvider uses httpx (consistent
with OllamaProvider), not the openai SDK."
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Iterator

import httpx

from core.interface.models import CompletionResponse, ProviderMessage

log = logging.getLogger(__name__)


class OpenAIProvider:
    """Inference provider for OpenAI's chat completions API.

    Uses raw httpx — not the openai Python SDK. Compatible with any
    OpenAI-compatible endpoint (OpenAI, Azure, Groq, Together, etc.).
    """

    provider_name = "openai"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str = "https://api.openai.com/v1",
        default_model: str = "gpt-4o",
        max_tokens: int = 4096,
        timeout: int = 120,
    ):
        self._api_key = api_key or os.environ.get("OPENAI_API_KEY")
        self._base_url = base_url.rstrip("/")
        self._default_model = default_model
        self._max_tokens = max_tokens
        self._client = httpx.Client(
            timeout=timeout,
            headers={"Authorization": f"Bearer {self._api_key}"} if self._api_key else {},
        )

    def generate(
        self,
        messages: list[ProviderMessage],
        *,
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        **kwargs,
    ) -> CompletionResponse:
        url = f"{self._base_url}/chat/completions"
        body = {
            "model": model or self._default_model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "temperature": temperature,
            "max_tokens": max_tokens or self._max_tokens,
            "stream": False,
        }

        try:
            t0 = time.monotonic()
            resp = self._client.post(url, json=body)
            resp.raise_for_status()
            data = resp.json()
            latency = int((time.monotonic() - t0) * 1000)

            choice = data["choices"][0]
            usage = data.get("usage", {})

            return CompletionResponse(
                text=choice["message"]["content"],
                model=data.get("model", model or self._default_model),
                provider=self.provider_name,
                input_tokens=usage.get("prompt_tokens", 0),
                output_tokens=usage.get("completion_tokens", 0),
                latency_ms=latency,
            )
        except Exception as e:
            log.error("OpenAIProvider.generate failed: %s", type(e).__name__)
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
        max_tokens: int | None = None,
        **kwargs,
    ) -> Iterator[str]:
        url = f"{self._base_url}/chat/completions"
        body = {
            "model": model or self._default_model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "temperature": temperature,
            "max_tokens": max_tokens or self._max_tokens,
            "stream": True,
        }

        try:
            with self._client.stream("POST", url, json=body) as resp:
                resp.raise_for_status()
                for line in resp.iter_lines():
                    if not line or not line.startswith("data: "):
                        continue
                    payload = line[6:]
                    if payload == "[DONE]":
                        break
                    chunk = json.loads(payload)
                    delta = chunk.get("choices", [{}])[0].get("delta", {})
                    content = delta.get("content", "")
                    if content:
                        yield content
        except Exception as e:
            log.error("OpenAIProvider.stream failed: %s", type(e).__name__)

    def count_tokens(self, text: str) -> int:
        try:
            import tiktoken
            enc = tiktoken.encoding_for_model(self._default_model)
            return len(enc.encode(text))
        except Exception:
            return int(len(text.split()) * 1.3)

    def is_available(self) -> bool:
        return bool(self._api_key)
