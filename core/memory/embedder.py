"""Embedding facade — thin delegation layer over EmbedderRegistry.

All embedding calls route through the EmbedderRegistry singleton.
If no embedder is registered, functions return zero-vectors (backward
compatible) rather than crashing.  The registry's ``_safe`` methods
return None on failure; this layer converts None to zero-vectors.

No ``import ollama`` anywhere in this file.
"""

from __future__ import annotations

import logging

from core.interface.config import EMBED_DIMS

log = logging.getLogger(__name__)


def embed_single(text: str) -> list[float]:
    """Embed text. Returns zero-vector if embedder unavailable."""
    from core.memory.embedder_registry import EmbedderRegistry

    result = EmbedderRegistry.get_instance().embed_single_safe(text)
    if result is None:
        return [0.0] * EMBED_DIMS
    return result


def embed_batch(texts: list[str]) -> list[list[float]]:
    """Batch embed. Returns zero-vectors if embedder unavailable."""
    from core.memory.embedder_registry import EmbedderRegistry

    result = EmbedderRegistry.get_instance().embed_batch_safe(texts)
    if result is None:
        return [[0.0] * EMBED_DIMS for _ in texts]
    return result


def check_health() -> bool:
    """True if embedder is registered and available."""
    from core.memory.embedder_registry import EmbedderRegistry

    return EmbedderRegistry.get_instance().is_available()
