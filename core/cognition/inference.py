"""Ollama local inference wrapper — generate, health check, model availability."""

from __future__ import annotations

import logging
from pathlib import Path

import ollama as _ollama

from core.interface.config import (
    INFERENCE_MAX_TOKENS,
    INFERENCE_MODEL,
    INFERENCE_TEMPERATURE,
    INFERENCE_TIMEOUT_SECONDS,
    INFERENCE_TOP_P,
    VAULT_DIR,
)

log = logging.getLogger(__name__)

_LOGPROBS_AVAILABLE: bool | None = None  # Cached after first probe


def get_inference_client() -> _ollama.Client:
    return _ollama.Client(timeout=INFERENCE_TIMEOUT_SECONDS)


def check_inference_model() -> bool:
    """Return True if INFERENCE_MODEL is pulled and available."""
    try:
        client = get_inference_client()
        models = client.list()
        available = [m.model for m in models.models]
        model_base = INFERENCE_MODEL.split(":")[0]
        return any(model_base in m for m in available)
    except Exception as e:
        log.debug("Inference model check failed: %s", e)
        return False


def validate_model_name(model_name: str) -> str | None:
    """Validate model exists in Ollama or matches cloud model. Returns error message or None."""
    from core.interface.config import CLOUD_MODEL
    if model_name == CLOUD_MODEL:
        return None
    try:
        client = get_inference_client()
        models = client.list()
        available = [m.model for m in models.models]
        model_base = model_name.split(":")[0]
        if any(model_base in m for m in available):
            return None
        return f"Model '{model_name}' not found. Available: {', '.join(available)}"
    except Exception as e:
        log.warning("Model validation failed (Ollama unreachable): %s", e)
        return None  # Allow through if Ollama is down — will fail at inference time


def check_logprob_support() -> bool:
    """Probe Ollama for logprob support. Caches result after first call."""
    global _LOGPROBS_AVAILABLE
    if _LOGPROBS_AVAILABLE is not None:
        return _LOGPROBS_AVAILABLE

    try:
        client = get_inference_client()
        resp = client.generate(
            model=INFERENCE_MODEL,
            prompt="Say hello.",
            options={"num_predict": 5, "temperature": 0.0},
        )
        _LOGPROBS_AVAILABLE = "logprobs" in resp and resp["logprobs"] is not None
    except Exception as e:
        log.debug("Logprob probe failed: %s", e)
        _LOGPROBS_AVAILABLE = False

    return _LOGPROBS_AVAILABLE


def generate_local(
    prompt: str,
    system: str | None = None,
    model: str | None = None,
    **option_overrides,
) -> dict:
    """Run local inference via Ollama. Returns dict with response, logprobs, eval stats.

    On error returns {"error": str, "response": ""}.
    """
    options = {
        "temperature": INFERENCE_TEMPERATURE,
        "top_p": INFERENCE_TOP_P,
        "num_predict": INFERENCE_MAX_TOKENS,
    }
    options.update(option_overrides)

    try:
        client = get_inference_client()
        kwargs: dict = {
            "model": model or INFERENCE_MODEL,
            "prompt": prompt,
            "options": options,
        }
        if system:
            kwargs["system"] = system

        resp = client.generate(**kwargs)
        return {
            "response": resp.get("response", ""),
            "logprobs": resp.get("logprobs"),
            "eval_count": resp.get("eval_count", 0),
            "eval_duration": resp.get("eval_duration", 0),
        }
    except _ollama.ResponseError as e:
        log.error("Ollama response error: %s", e)
        return {"error": str(e), "response": ""}
    except Exception as e:
        log.error("Inference failed: %s", e)
        return {"error": str(e), "response": ""}


def generate_local_stream(
    prompt: str,
    system: str | None = None,
    model: str | None = None,
    **option_overrides,
) -> "Iterator[dict]":
    """Yield chunks from Ollama streaming. Final chunk has done=True + logprobs."""
    from typing import Iterator

    options = {
        "temperature": INFERENCE_TEMPERATURE,
        "top_p": INFERENCE_TOP_P,
        "num_predict": INFERENCE_MAX_TOKENS,
    }
    options.update(option_overrides)

    try:
        client = get_inference_client()
        kwargs: dict = {
            "model": model or INFERENCE_MODEL,
            "prompt": prompt,
            "options": options,
            "stream": True,
        }
        if system:
            kwargs["system"] = system

        for chunk in client.generate(**kwargs):
            done = chunk.get("done", False)
            yield {
                "delta": chunk.get("response", ""),
                "done": done,
                "logprobs": chunk.get("logprobs") if done else None,
                "eval_count": chunk.get("eval_count", 0) if done else 0,
                "eval_duration": chunk.get("eval_duration", 0) if done else 0,
            }
    except Exception as e:
        log.error("Streaming inference failed: %s", e)
        yield {"delta": "", "done": True, "error": str(e), "logprobs": None, "eval_count": 0, "eval_duration": 0}


def load_system_prompt(pattern_name: str) -> str:
    """Read system prompt from vault/patterns/{pattern_name}/.

    Supports persona splitting for 'sovereign' pattern:
    - If OIKOS_PERSONA='engineer', loads 'engineer.md'
    - Default loads 'sovereign.md'
    - Fallback to 'system.md' if specific file missing
    """
    import os
    
    base_dir = VAULT_DIR / "patterns" / pattern_name
    
    # Special handling for sovereign identity split
    if pattern_name == "sovereign":
        persona = os.environ.get("OIKOS_PERSONA", "sovereign").lower()
        
        # Map generic 'engineer' or 'claude' to engineer.md
        if persona in ("engineer", "claude", "kp-claude"):
            target_file = "engineer.md"
        else:
            target_file = "sovereign.md"
            
        path = base_dir / target_file
        if path.exists():
            return path.read_text(encoding="utf-8")
            
    # Fallback to standard system.md
    path = base_dir / "system.md"
    if not path.exists():
        log.warning("Pattern not found: %s", path)
        return ""
    return path.read_text(encoding="utf-8")
