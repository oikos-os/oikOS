"""Ollama embedding wrapper — CPU-only, batched."""

from __future__ import annotations

import logging
import os

import ollama as _ollama

from core.interface.config import EMBED_BATCH_SIZE, EMBED_DIMS, EMBED_MODEL

log = logging.getLogger(__name__)

# Force CPU-only for embeddings — leave GPU free for inference
os.environ.setdefault("OLLAMA_NUM_GPU", "0")


def get_client() -> _ollama.Client:
    return _ollama.Client()


def embed_single(text: str) -> list[float]:
    """Embed a single text, returns 768-dim float list."""
    if not text or not text.strip():
        # Return zero vector for empty input
        log.warning("embed_single called with empty text, returning zero vector")
        return [0.0] * EMBED_DIMS

    client = get_client()
    resp = client.embed(model=EMBED_MODEL, input=text)

    if not resp.get("embeddings") or len(resp["embeddings"]) == 0:
        log.error("Ollama returned empty embeddings array, returning zero vector")
        return [0.0] * EMBED_DIMS

    vec = resp["embeddings"][0]
    if len(vec) != EMBED_DIMS:
        log.warning("Expected %d dims, got %d", EMBED_DIMS, len(vec))
    return vec


def embed_batch(texts: list[str]) -> list[list[float]]:
    """Embed a list of texts in sub-batches of EMBED_BATCH_SIZE."""
    client = get_client()
    all_vecs: list[list[float]] = []
    for i in range(0, len(texts), EMBED_BATCH_SIZE):
        batch = texts[i : i + EMBED_BATCH_SIZE]
        resp = client.embed(model=EMBED_MODEL, input=batch)
        all_vecs.extend(resp["embeddings"])
    return all_vecs


def check_health() -> bool:
    """Return True if Ollama is reachable and embed model is available."""
    try:
        client = get_client()
        models = client.list()
        available = [m.model for m in models.models]
        # Check for model name (with or without :latest tag)
        model_base = EMBED_MODEL.split(":")[0]
        return any(model_base in m for m in available)
    except Exception as e:
        log.debug("Ollama health check failed: %s", e)
        return False
