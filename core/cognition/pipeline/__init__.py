"""Pipeline package — staged inference processing."""

from __future__ import annotations

import re
from typing import NamedTuple

from core.cognition.pipeline.trace import RoutingTrace
from core.interface.models import (
    CompiledContext, ConfidenceResult, ContradictionResult,
    PIIResult, RoutingDecision,
)


class PreparedContext(NamedTuple):
    decision: RoutingDecision
    pii_result: PIIResult
    effective_query: str
    pii_scrubbed: bool
    compiled: CompiledContext
    context_block: str
    system_prompt: str | None
    full_prompt: str
    session: dict
    qhash: str


class PostProcessResult(NamedTuple):
    text: str
    confidence: ConfidenceResult
    contradiction: ContradictionResult | None
    warnings: list[str]
    is_hard_veto: bool


# Matches classifier JSON that bleeds into model output
_JSON_PREAMBLE_RE = re.compile(
    r'^\s*\{[^{}]*"(?:contains_assertion|assertion_type|is_coherent|coherence_score|response)"[^{}]*\}\s*',
)


def strip_json_preamble(text: str) -> str:
    """Remove classifier JSON that occasionally bleeds into model output."""
    cleaned = _JSON_PREAMBLE_RE.sub("", text, count=1)
    return cleaned if cleaned.strip() else text


MISSION_KEYWORDS = frozenset({
    "give up", "giving up", "quit", "quitting", "abandon", "stop pursuing",
    "corporate", "promotion", "safe path", "day job", "settle",
    "stop", "pause indefinitely", "not worth it",
})
