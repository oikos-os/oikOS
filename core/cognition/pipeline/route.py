"""Pipeline stage: routing decision (force flags, complexity, embedding, auto-route)."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from core.cognition.pipeline.trace import RoutingTrace
from core.interface.models import PIIResult, RoutingDecision, RouteType

log = logging.getLogger(__name__)


def make_routing_decision(
    effective_query: str,
    pii_result: PIIResult,
    qhash: str,
    force_local: bool = False,
    force_cloud: bool = False,
    trace: RoutingTrace | None = None,
) -> RoutingDecision:
    """Determine routing: force flags -> complexity pre-score -> embedding -> auto route."""
    ts = datetime.now(timezone.utc).isoformat()

    if force_local:
        return RoutingDecision(
            route=RouteType.LOCAL,
            reason="Forced local by user flag",
            confidence=None,
            pii_detected=pii_result.has_pii,
            query_hash=qhash,
            timestamp=ts,
        )

    if force_cloud:
        return RoutingDecision(
            route=RouteType.CLOUD,
            reason="Forced cloud by user flag",
            confidence=None,
            pii_detected=pii_result.has_pii,
            query_hash=qhash,
            timestamp=ts,
        )

    # Complexity pre-score (non-blocking)
    complexity = None
    try:
        from core.cognition.complexity import score_complexity
        complexity = score_complexity(effective_query)
    except (ValueError, RuntimeError) as e:
        log.warning("Complexity scoring failed: %s", e)

    # Embedding (non-blocking)
    query_vec = None
    try:
        from core.memory.embedder import embed_single
        query_vec = embed_single(effective_query)
    except (ConnectionError, RuntimeError):
        pass

    from core.cognition.routing import route_query
    result = route_query(effective_query, pii_result, None, query_vector=query_vec, complexity=complexity)
    if trace is not None:
        if result.cosine_gate_fired:
            trace.cosine_gate_fired = True
        if complexity and complexity.get("skip_local"):
            trace.complexity = "COMPLEX"
            if result.route == RouteType.CLOUD:
                trace.confidence_escalated = True
        elif complexity:
            trace.complexity = "SIMPLE" if complexity.get("penalty", 0) < 50 else "MODERATE"
    return result
