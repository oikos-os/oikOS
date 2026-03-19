"""Privacy middleware — enforces NEVER_LEAVE/SENSITIVE/SAFE tiers on input and output."""

from __future__ import annotations

import json
import logging
from typing import Any, Callable

from core.cognition.providers.content_classifier import ContentClassifier
from core.framework.exceptions import PrivacyViolation
from core.framework.middleware.base import MiddlewareContext
from core.interface.models import DataTier

log = logging.getLogger(__name__)


class PrivacyMiddleware:
    """Classifies input/output content and enforces privacy tiers.

    Input phase: blocks NEVER_LEAVE on remote clients, anonymizes SENSITIVE.
    Output phase: redacts NEVER_LEAVE from results, deanonymizes SENSITIVE.
    """

    def __init__(self, classifier: ContentClassifier | None = None):
        self._classifier = classifier or ContentClassifier()

    async def __call__(self, ctx: MiddlewareContext, call_next: Callable) -> Any:
        # Input classification
        input_text = json.dumps(ctx.arguments, default=str)
        tier = self._classifier.classify(input_text)
        ctx.extras["privacy_tier"] = tier

        if tier == DataTier.NEVER_LEAVE:
            is_remote = ctx.extras.get("transport") != "stdio"
            if is_remote:
                # NEVER_LEAVE content never crosses the wire, period.
                # Even tools declared as NEVER_LEAVE are blocked on remote transports
                # because the arguments have already been transmitted.
                raise PrivacyViolation(ctx.tool_name, "NEVER_LEAVE")

        if tier == DataTier.SENSITIVE:
            anon_text, mapping = self._classifier.anonymize(input_text)
            ctx.extras["anonymization_map"] = mapping
            # Re-parse anonymized args back
            try:
                ctx.arguments = json.loads(anon_text)
            except (json.JSONDecodeError, TypeError):
                pass  # Keep original if re-parse fails

        # Execute downstream
        result = await call_next()

        # Output classification
        if result is not None:
            result_text = str(result)
            output_tier = self._classifier.classify(result_text)

            if output_tier == DataTier.NEVER_LEAVE:
                log.warning("NEVER_LEAVE content in output of %s — redacting", ctx.tool_name)
                return "[REDACTED: contains protected content]"

            mapping = ctx.extras.get("anonymization_map")
            if mapping and isinstance(result, str):
                result = self._classifier.deanonymize(result, mapping)

        return result
