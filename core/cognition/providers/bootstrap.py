"""Provider bootstrap — create and register all providers at startup.

T-047: Reads providers.toml first. Falls back to env-based registration
if no TOML exists. Local Ollama is ALWAYS registered as first provider
and non-configurable fallback (SYNTH ruling #6).
"""

from __future__ import annotations

import logging
import os
from typing import Any

from core.cognition.providers.config_loader import (
    ConfigError,
    load_providers_config,
)
from core.cognition.providers.registry import ProviderRegistry
from core.interface.config import (
    INFERENCE_MODEL,
    INFERENCE_TIMEOUT_SECONDS,
    PROVIDER_ANTHROPIC_MAX_TOKENS,
    PROVIDER_ANTHROPIC_MODEL,
    PROVIDER_OLLAMA_BASE_URL,
)

log = logging.getLogger(__name__)

# Maps TOML type → (module, class, env_key_required)
_PROVIDER_MAP = {
    "ollama": ("core.cognition.providers.ollama_provider", "OllamaProvider", None),
    "anthropic": ("core.cognition.providers.anthropic_provider", "AnthropicProvider", "ANTHROPIC_API_KEY"),
    "gemini": ("core.cognition.providers.gemini_provider", "GeminiProvider", "GEMINI_API_KEY"),
    "openai": ("core.cognition.providers.openai_provider", "OpenAIProvider", "OPENAI_API_KEY"),
    "openai-local": ("core.cognition.providers.openai_provider", "OpenAIProvider", None),
    "litellm": ("core.cognition.providers.litellm_provider", "LiteLLMProvider", None),
}


def create_registry() -> ProviderRegistry:
    """Create a ProviderRegistry with all available providers.

    Reads providers.toml if present. Falls back to env-based defaults.
    Local Ollama is always registered first (doctrine: local-first).
    """
    try:
        config = load_providers_config()
    except ConfigError as exc:
        log.warning("providers.toml error: %s — falling back to env defaults", exc)
        return _create_registry_from_env()

    return _create_registry_from_config(config)


def _create_registry_from_config(config: dict[str, Any]) -> ProviderRegistry:
    """Build registry from parsed TOML config."""
    registry = ProviderRegistry()
    providers = config.get("providers", {})
    general = config.get("general", {})

    # Invariant: local Ollama always registered first
    _ensure_local(registry, providers)

    # Register remaining providers
    for name, prov_config in providers.items():
        if name == "local":
            continue  # already registered
        ptype = prov_config.get("type", "")
        entry = _PROVIDER_MAP.get(ptype)
        if entry is None:
            log.warning("Unknown provider type '%s' for '%s' — skipping", ptype, name)
            continue

        module_path, class_name, env_key = entry

        # Cloud providers require API key in environment (security: never in TOML)
        if env_key and not os.environ.get(env_key):
            log.debug("Skipping '%s' — %s not set", name, env_key)
            continue

        try:
            provider = _instantiate(module_path, class_name, prov_config)
            if ptype == "litellm" and not provider.is_available():
                log.debug("Skipping '%s' — litellm not available", name)
                continue
            registry.register(name, provider)
        except Exception as exc:
            log.warning("Failed to initialize provider '%s': %s", name, exc)

    # Set default from config
    default_name = general.get("default", "local")
    if default_name in registry.list_all():
        registry.set_default(default_name)

    log.info("Provider registry initialized: %s (default: %s)",
             registry.list_all(), default_name)
    return registry


def _ensure_local(registry: ProviderRegistry, providers: dict) -> None:
    """Always register local Ollama as the first provider."""
    local_config = providers.get("local", {})
    from core.cognition.providers.ollama_provider import OllamaProvider
    registry.register(
        "local",
        OllamaProvider(
            base_url=local_config.get("base_url", PROVIDER_OLLAMA_BASE_URL),
            default_model=local_config.get("default_model", INFERENCE_MODEL),
            timeout=local_config.get("timeout", INFERENCE_TIMEOUT_SECONDS),
        ),
    )


def _instantiate(module_path: str, class_name: str, config: dict) -> Any:
    """Lazy-import and instantiate a provider from its config."""
    import importlib
    mod = importlib.import_module(module_path)
    cls = getattr(mod, class_name)

    # Build kwargs from config, filtering out 'type'
    kwargs = {k: v for k, v in config.items() if k != "type"}
    return cls(**kwargs)


def _create_registry_from_env() -> ProviderRegistry:
    """Legacy env-based bootstrap (pre-TOML backward compat)."""
    registry = ProviderRegistry()

    from core.cognition.providers.ollama_provider import OllamaProvider
    registry.register(
        "local",
        OllamaProvider(
            base_url=PROVIDER_OLLAMA_BASE_URL,
            default_model=INFERENCE_MODEL,
            timeout=INFERENCE_TIMEOUT_SECONDS,
        ),
    )

    if os.environ.get("ANTHROPIC_API_KEY"):
        from core.cognition.providers.anthropic_provider import AnthropicProvider
        registry.register(
            "claude",
            AnthropicProvider(
                default_model=PROVIDER_ANTHROPIC_MODEL,
                max_tokens=PROVIDER_ANTHROPIC_MAX_TOKENS,
            ),
        )

    if os.environ.get("GEMINI_API_KEY"):
        from core.cognition.providers.gemini_provider import GeminiProvider
        registry.register("gemini", GeminiProvider())

    if os.environ.get("OPENAI_API_KEY"):
        from core.cognition.providers.openai_provider import OpenAIProvider
        registry.register("openai", OpenAIProvider())

    try:
        from core.cognition.providers.litellm_provider import LiteLLMProvider
        p = LiteLLMProvider()
        if p.is_available():
            registry.register("litellm", p)
    except Exception:
        pass

    log.info("Provider registry initialized (env): %s (default: local)", registry.list_all())
    return registry
