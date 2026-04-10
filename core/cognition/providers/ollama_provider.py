"""OllamaProvider — httpx to Ollama's OpenAI-compatible chat endpoint."""

from __future__ import annotations

import json
import logging
import time
from typing import Iterator

import httpx

from core.interface.models import CompletionResponse, ProviderMessage

log = logging.getLogger(__name__)


class OllamaProvider:
    """Inference provider using Ollama's OpenAI-compatible API.

    Works with any OpenAI-compatible server (Ollama, vLLM, LM Studio, llama.cpp).
    """

    provider_name = "ollama"

    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        default_model: str = "qwen2.5:14b",
        timeout: int = 60,
    ):
        self._base_url = base_url.rstrip("/")
        self._default_model = default_model
        self._timeout = timeout
        self._client = httpx.Client(timeout=timeout)

    def generate(
        self,
        messages: list[ProviderMessage],
        *,
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        **kwargs,
    ) -> CompletionResponse:
        url = f"{self._base_url}/v1/chat/completions"
        body = {
            "model": model or self._default_model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "temperature": temperature,
            "max_tokens": max_tokens,
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
            log.error("OllamaProvider.generate failed: %s", e)
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
        url = f"{self._base_url}/v1/chat/completions"
        body = {
            "model": model or self._default_model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
        }

        try:
            with self._client.stream("POST", url, json=body) as resp:
                resp.raise_for_status()
                for line in resp.iter_lines():
                    if not line or not line.startswith("data: "):
                        continue
                    payload = line[6:]  # strip "data: "
                    if payload == "[DONE]":
                        break
                    chunk = json.loads(payload)
                    delta = chunk.get("choices", [{}])[0].get("delta", {})
                    content = delta.get("content", "")
                    if content:
                        yield content
        except Exception as e:
            log.error("OllamaProvider.stream failed: %s", e)

    def count_tokens(self, text: str) -> int:
        return int(len(text.split()) * 1.3)

    def is_available(self) -> bool:
        try:
            resp = self._client.get(f"{self._base_url}/api/tags")
            resp.raise_for_status()
            return True
        except Exception:
            return False
