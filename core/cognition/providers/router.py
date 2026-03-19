"""PrivacyAwareRouter — posture-based provider selection with privacy enforcement.

OPT-01 (T-047): Adaptive model selection — routes to model tier based on
query complexity. Simple → 7B, Moderate → 14B, Complex → cloud model.
"""

from __future__ import annotations

import logging
import re
from typing import Any, TYPE_CHECKING

from core.cognition.providers.content_classifier import ContentClassifier
from core.cognition.providers.registry import ProviderRegistry
from core.interface.models import CompletionResponse, DataTier, ProviderMessage, RoutingPosture

if TYPE_CHECKING:
    from core.cognition.providers.protocol import InferenceProvider

log = logging.getLogger(__name__)

# Complexity heuristic signals
_COMPLEX_KEYWORDS = re.compile(
    r"(?i)\b(strateg\w*|analy[zs]\w*|compar\w*|framework|architect\w*|debug\w*|refactor\w*|"
    r"code.generat\w*|implement\w*|design.pattern|multi[.-]step)"
)
_LENGTH_COMPLEX_THRESHOLD = 40  # words

# Default model tiers (overridden by providers.toml [model_tiers])
_DEFAULT_MODEL_TIERS = {
    "simple": "qwen2.5:7b",
    "moderate": "qwen2.5:14b",
    "complex": "gemini-2.5-pro",
}


class PrivacyAwareRouter:
    """Routes requests to providers based on posture, complexity, and privacy tier.

    OPT-01: When model_tiers is set, selects model size by query complexity.
    """

    def __init__(
        self,
        registry: ProviderRegistry,
        local_name: str = "local",
        posture: RoutingPosture = RoutingPosture.BALANCED,
        model_tiers: dict[str, str] | None = None,
    ):
        self._registry = registry
        self._local_name = local_name
        self.posture = posture
        self._classifier = ContentClassifier()
        self._model_tiers = model_tiers or _DEFAULT_MODEL_TIERS

    def route(
        self,
        messages: list[ProviderMessage],
        *,
        provider: str | None = None,
        cloud_name: str | None = None,
        **kwargs,
    ) -> CompletionResponse:
        """Route messages to the appropriate provider and return a CompletionResponse.

        Privacy enforcement:
        - NEVER_LEAVE: forces local, regardless of provider arg
        - SENSITIVE: anonymizes before cloud, deanonymizes response
        - SAFE: routes as-is
        """
        all_content = " ".join(m.content for m in messages)
        tier = self._classifier.classify(all_content)

        target_name = self._resolve_provider(provider, cloud_name, all_content, tier)

        # Privacy enforcement
        if tier == DataTier.NEVER_LEAVE and target_name != self._local_name:
            log.warning("NEVER_LEAVE content forced to local (was: %s)", target_name)
            target_name = self._local_name

        target = self._registry.get(target_name)

        # OPT-01: Adaptive model selection based on complexity
        if "model" not in kwargs:
            kwargs["model"] = self._select_model(all_content, target_name)

        if tier == DataTier.SENSITIVE and target_name != self._local_name:
            return self._route_with_anonymization(messages, target, **kwargs)

        return target.generate(messages, **kwargs)

    def route_stream(
        self,
        messages: list[ProviderMessage],
        *,
        provider: str | None = None,
        cloud_name: str | None = None,
        **kwargs,
    ):
        """Stream variant of route. Yields text deltas."""
        all_content = " ".join(m.content for m in messages)
        tier = self._classifier.classify(all_content)

        target_name = self._resolve_provider(provider, cloud_name, all_content, tier)

        if tier == DataTier.NEVER_LEAVE and target_name != self._local_name:
            log.warning("NEVER_LEAVE content forced to local (stream, was: %s)", target_name)
            target_name = self._local_name

        target = self._registry.get(target_name)
        # Streaming with anonymization not supported — fall back to local for SENSITIVE
        if tier == DataTier.SENSITIVE and target_name != self._local_name:
            log.info("SENSITIVE content in stream mode — routing local")
            target_name = self._local_name
            target = self._registry.get(self._local_name)

        # OPT-01: Adaptive model selection
        if "model" not in kwargs:
            kwargs["model"] = self._select_model(all_content, target_name)

        yield from target.stream(messages, **kwargs)

    def _resolve_provider(
        self,
        explicit: str | None,
        cloud_name: str | None,
        content: str,
        tier: DataTier,
    ) -> str:
        """Determine which provider to use based on posture and complexity."""
        if explicit:
            return explicit

        cloud = cloud_name or self._find_cloud_provider()

        if self.posture == RoutingPosture.CONSERVATIVE:
            return self._local_name

        if self.posture == RoutingPosture.AGGRESSIVE:
            return cloud or self._local_name

        # BALANCED: only COMPLEX escalates to cloud; MODERATE stays local
        complexity = self._classify_complexity(content)
        if complexity == "COMPLEX" and cloud:
            return cloud
        return self._local_name

    def _find_cloud_provider(self) -> str | None:
        """Find the first available cloud provider."""
        for name in self._registry.list_all():
            if name != self._local_name:
                p = self._registry.get(name)
                if p.is_available():
                    return name
        return None

    def _route_with_anonymization(
        self,
        messages: list[ProviderMessage],
        target: InferenceProvider,
        **kwargs,
    ) -> CompletionResponse:
        """Anonymize messages, route to cloud, deanonymize response."""
        anon_messages = []
        combined_map: dict[str, str] = {}
        for m in messages:
            anon_text, mapping = self._classifier.anonymize(m.content)
            anon_messages.append(ProviderMessage(role=m.role, content=anon_text, name=m.name))
            combined_map.update(mapping)

        result = target.generate(anon_messages, **kwargs)
        if combined_map:
            result = CompletionResponse(
                text=self._classifier.deanonymize(result.text, combined_map),
                model=result.model,
                provider=result.provider,
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
                latency_ms=result.latency_ms,
                logprobs=result.logprobs,
                raw=result.raw,
            )
        return result

    def _classify_complexity(self, content: str) -> str:
        """Rule-based complexity classification (~1ms, zero LLM cost).

        Returns: "SIMPLE", "MODERATE", or "COMPLEX"
        """
        score = 0
        words = content.split()

        if len(words) > _LENGTH_COMPLEX_THRESHOLD:
            score += 2

        matches = len(_COMPLEX_KEYWORDS.findall(content))
        score += min(matches, 3)

        if score >= 4:
            return "COMPLEX"
        if score >= 2:
            return "MODERATE"
        return "SIMPLE"

    def _select_model(self, content: str, target_name: str) -> str | None:
        """OPT-01: Select model based on query complexity tier.

        Only applies tier model when the target provider can handle it:
        - simple/moderate tiers apply only to local provider (Ollama models)
        - complex tier applies only to cloud providers
        Returns None to use provider's own default_model.
        """
        complexity = self._classify_complexity(content)
        tier_key = complexity.lower()
        model = self._model_tiers.get(tier_key)

        if not model:
            return None

        # Don't send local model names to cloud providers or vice versa
        is_local = target_name == self._local_name
        if tier_key in ("simple", "moderate") and not is_local:
            return None  # Cloud provider uses its own default
        if tier_key == "complex" and is_local:
            return None  # Local provider uses its own default

        log.debug("OPT-01: complexity=%s -> model=%s (provider=%s)", complexity, model, target_name)
        return model
