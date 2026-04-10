"""Multi-provider inference abstraction (T-037, T-047)."""

from core.cognition.providers.protocol import InferenceProvider
from core.cognition.providers.registry import ProviderRegistry
from core.cognition.providers.bootstrap import create_registry
from core.cognition.providers.config_loader import load_providers_config, ConfigError

__all__ = [
    "InferenceProvider",
    "ProviderRegistry",
    "create_registry",
    "load_providers_config",
    "ConfigError",
]
