"""EmbedderRegistry — singleton registry for the active embedding provider.

Simpler than ProviderRegistry: embeddings are not a routing decision.
You have one active embedder or you don't.

The ``_safe`` methods wrap ALL exceptions with try/except and return None,
enabling callers to fall back to BM25-only search gracefully.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.memory.embedder_protocol import EmbedderProvider

log = logging.getLogger(__name__)


class EmbedderRegistry:
    """Singleton registry for the active embedding provider."""

    _instance: EmbedderRegistry | None = None
    _provider: EmbedderProvider | None = None

    @classmethod
    def get_instance(cls) -> EmbedderRegistry:
        """Return the singleton instance, creating it if needed."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """Clear the singleton and any registered provider. For test isolation."""
        cls._instance = None
        cls._provider = None

    def register(self, provider: EmbedderProvider) -> None:
        """Set the active embedding provider."""
        self._provider = provider
        log.info("Embedder registered: %s", getattr(provider, "provider_name", "unknown"))

    def get(self) -> EmbedderProvider | None:
        """Return the active embedder, or None if none registered."""
        return self._provider

    def is_available(self) -> bool:
        """True if a provider is registered AND reports itself available."""
        if self._provider is None:
            return False
        try:
            return self._provider.is_available()
        except Exception:
            log.debug("Embedder availability check failed", exc_info=True)
            return False

    def embed_single_safe(self, text: str) -> list[float] | None:
        """Embed text, returning None if unavailable or on any exception.

        None signals callers to use BM25-only fallback rather than
        polluting search with zero-vectors.
        """
        if self._provider is None:
            return None
        try:
            return self._provider.embed_single(text)
        except Exception:
            log.debug("embed_single_safe failed", exc_info=True)
            return None

    def embed_batch_safe(self, texts: list[str]) -> list[list[float]] | None:
        """Batch embed, returning None if unavailable or on any exception.

        Same None-means-fallback pattern as embed_single_safe.
        """
        if self._provider is None:
            return None
        try:
            return self._provider.embed_batch(texts)
        except Exception:
            log.debug("embed_batch_safe failed", exc_info=True)
            return None
