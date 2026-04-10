"""Input classification — adversarial detection and PII handling."""

from __future__ import annotations

import logging
from typing import NamedTuple

from core.identity.input_guard import detect_adversarial
from core.interface.config import INFERENCE_MODEL
from core.interface.models import InferenceResponse, PIIResult, RouteType
from core.safety.pii import detect_pii, log_detection, scrub_pii

log = logging.getLogger(__name__)


class ClassifyResult(NamedTuple):
    """Output of input classification stage."""
    effective_query: str
    pii_result: PIIResult
    pii_scrubbed: bool


def classify_input(
    query: str,
    qhash: str,
    skip_pii_scrub: bool = False,
) -> ClassifyResult | InferenceResponse:
    """Stages 0c-2: adversarial detection, PII detect, PII scrub.

    Returns ClassifyResult on success, or InferenceResponse on hard reject.
    """
    # 0c. Adversarial input detection
    adv_result = detect_adversarial(query)
    if adv_result.is_adversarial:
        log.warning(
            "[ADVERSARIAL QUERY] severity=%d patterns=%s",
            adv_result.severity, adv_result.matched_patterns,
        )
        if adv_result.severity >= 6:
            log.warning(
                "Adversarial input blocked. Patterns: %s",
                ", ".join(adv_result.matched_patterns),
            )
            return InferenceResponse(
                text="Query rejected due to policy violation.",
                route=RouteType.LOCAL,
                model_used=INFERENCE_MODEL,
                confidence=0.0,
                pii_scrubbed=False,
            )

    # 1. PII detection
    if skip_pii_scrub:
        pii_result = PIIResult(has_pii=False, entities=[])
    else:
        pii_result = detect_pii(query)
        if pii_result.has_pii:
            log_detection(pii_result, qhash)

    # 2. Determine effective query
    effective_query = query
    pii_scrubbed = False
    if pii_result.has_pii:
        scrub_result = scrub_pii(query)
        if scrub_result.scrubbed_text and scrub_result.scrubbed_text != query:
            effective_query = scrub_result.scrubbed_text
            pii_scrubbed = True
            # T-119: emit notification event for PII anonymization (MUST tier)
            try:
                from core.autonomic.events import emit_event
                emit_event("safety", "pii_anonymized", {
                    "entity_count": len(pii_result.entities),
                    "query_hash": qhash,
                })
            except Exception as e:
                log.debug("pii_anonymized emit suppressed: %s", e)

    return ClassifyResult(
        effective_query=effective_query,
        pii_result=pii_result,
        pii_scrubbed=pii_scrubbed,
    )
