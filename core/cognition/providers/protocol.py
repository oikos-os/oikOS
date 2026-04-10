"""InferenceProvider Protocol — the contract all providers implement."""

from __future__ import annotations

from typing import Iterator, Protocol, runtime_checkable

from core.interface.models import CompletionResponse, ProviderMessage


@runtime_checkable
class InferenceProvider(Protocol):
    """Contract for inference providers. All methods are synchronous.

    Note: is_available() is an engineer extension beyond the SYNTH-specified
    interface (generate, stream, count_tokens). Added for registry health checks.
    """

    provider_name: str

    def generate(
        self,
        messages: list[ProviderMessage],
        *,
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        **kwargs,
    ) -> CompletionResponse: ...

    def stream(
        self,
        messages: list[ProviderMessage],
        *,
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        **kwargs,
    ) -> Iterator[str]: ...

    def count_tokens(self, text: str) -> int: ...

    def is_available(self) -> bool: ...
