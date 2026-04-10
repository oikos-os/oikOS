"""ProviderRegistry — central registry for inference providers."""

from __future__ import annotations

import logging

from core.cognition.providers.protocol import InferenceProvider

log = logging.getLogger(__name__)


class ProviderRegistry:
    """Register, retrieve, and list inference providers."""

    def __init__(self):
        self._providers: dict[str, InferenceProvider] = {}
        self._default: str | None = None

    def register(self, name: str, provider: InferenceProvider) -> None:
        self._providers[name] = provider
        if self._default is None:
            self._default = name
        log.info("Provider registered: %s", name)

    def get(self, name: str) -> InferenceProvider:
        if name not in self._providers:
            raise KeyError(f"Unknown provider: '{name}'. Available: {list(self._providers)}")
        return self._providers[name]

    def get_default(self) -> InferenceProvider:
        if self._default is None:
            raise ValueError("No providers registered")
        return self._providers[self._default]

    def set_default(self, name: str) -> None:
        if name not in self._providers:
            raise KeyError(f"Unknown provider: '{name}'. Available: {list(self._providers)}")
        self._default = name
        log.info("Default provider set: %s", name)

    def list_available(self) -> list[str]:
        return [name for name, p in self._providers.items() if p.is_available()]

    def list_all(self) -> list[str]:
        return list(self._providers.keys())

    def get_default_name(self) -> str | None:
        return self._default
