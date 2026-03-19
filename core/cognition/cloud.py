"""Cloud bridge — Google GenAI API wrapper with retry and streaming."""

from __future__ import annotations

import logging
import os
import time
from typing import Iterator

from google import genai
from google.genai import types
from google.genai.errors import APIError

from core.interface.config import CLOUD_MAX_TOKENS, CLOUD_MODEL, CLOUD_TIMEOUT_SECONDS
from core.interface.models import CloudResponse

log = logging.getLogger(__name__)

_client: genai.Client | None = None
_model_validated: bool = False


def get_cloud_client() -> genai.Client:
    """Lazy-load Gemini client. Raises ValueError if no API key."""
    global _client
    if _client is not None:
        return _client

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY not set — cloud bridge unavailable")

    _client = genai.Client(api_key=api_key)
    return _client


def _check_cloud_model(client: genai.Client, model: str) -> None:
    """Validate cloud model exists on first call per session. Emits error event on failure."""
    global _model_validated
    if _model_validated:
        return

    try:
        client.models.get(model=model)
        _model_validated = True
        log.info("Cloud model validated: %s", model)
    except APIError as e:
        from core.autonomic.events import emit_event
        emit_event("cloud", "model_health_check_failed", {
            "model": model,
            "error": str(e),
            "code": getattr(e, "code", None),
        })
        log.error("Cloud model health check FAILED for %s: %s", model, e)
        _model_validated = True  # Don't re-check every call, emit once
        raise ValueError(f"Cloud model '{model}' unavailable: {e}") from e


def send_to_cloud(
    query: str,
    context: str,
    system: str = "",
    model: str | None = None,
) -> CloudResponse:
    """Synchronous cloud inference. Returns CloudResponse with token usage.

    Retries once on server error. No retry on 4xx.
    """
    client = get_cloud_client()
    model = model or CLOUD_MODEL
    _check_cloud_model(client, model)

    prompt = f"{context}\n\n---\nQuery: {query}"

    config = types.GenerateContentConfig(
        max_output_tokens=CLOUD_MAX_TOKENS,
        system_instruction=system if system else None,
    )

    last_error: Exception | None = None
    for attempt in range(2):
        try:
            t0 = time.monotonic()
            resp = client.models.generate_content(
                model=model,
                contents=prompt,
                config=config,
            )
            latency = int((time.monotonic() - t0) * 1000)

            usage = resp.usage_metadata
            input_tokens = getattr(usage, "prompt_token_count", 0) if usage else 0
            output_tokens = getattr(usage, "candidates_token_count", 0) if usage else 0

            text = resp.text if hasattr(resp, "text") and resp.text else ""

            return CloudResponse(
                text=text,
                model=model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                latency_ms=latency,
            )
        except APIError as e:
            last_error = e
            status_code = getattr(e, "code", 500)
            if attempt == 0 and status_code >= 500:
                log.warning("Cloud attempt %d failed (%s), retrying...", attempt + 1, type(e).__name__)
                continue
            elif attempt == 0 and status_code == 429:
                log.warning("Cloud attempt %d rate limited, retrying...", attempt + 1)
                time.sleep(1.0)
                continue
            raise e

    raise last_error  # type: ignore[misc]


def stream_cloud(
    query: str,
    context: str,
    system: str = "",
    model: str | None = None,
) -> Iterator[str]:
    """Yields text deltas from Gemini streaming API."""
    client = get_cloud_client()
    model = model or CLOUD_MODEL
    _check_cloud_model(client, model)

    prompt = f"{context}\n\n---\nQuery: {query}"

    config = types.GenerateContentConfig(
        max_output_tokens=CLOUD_MAX_TOKENS,
        system_instruction=system if system else None,
    )

    response_stream = client.models.generate_content_stream(
        model=model,
        contents=prompt,
        config=config,
    )
    for chunk in response_stream:
        if chunk.text:
            yield chunk.text
