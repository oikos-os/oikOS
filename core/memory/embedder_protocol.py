"""EmbedderProvider Protocol -- the contract all embedder providers implement."""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class EmbedderProvider(Protocol):
    """Contract for embedding providers. All methods are synchronous.

    Mirrors the InferenceProvider pattern from core.cognition.providers.protocol.
    """

    provider_name: str
    dims: int

    def embed_single(self, text: str) -> list[float]: ...

    def embed_batch(self, texts: list[str]) -> list[list[float]]: ...

    def is_available(self) -> bool: ...
