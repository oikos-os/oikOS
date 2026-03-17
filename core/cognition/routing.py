"""Query routing engine — PII gate, confidence gate, force-local patterns."""

from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import datetime, timezone

from core.interface.config import (
    ROUTING_CONFIDENCE_THRESHOLD,
    ROUTING_FORCE_LOCAL_PATTERNS,
    ROUTING_LOG_DIR,
)
from core.interface.models import ConfidenceResult, PIIResult, RoutingDecision, RouteType

log = logging.getLogger(__name__)


def query_hash(query: str) -> str:
    return hashlib.sha256(query.encode("utf-8")).hexdigest()[:16]


def route_query(
    query: str,
    pii_result: PIIResult,
    confidence: ConfidenceResult | None,
    query_vector: list[float] | None = None,
    complexity: dict | None = None,
) -> RoutingDecision:
    """Determine routing: PII gate → force-local → cosine → complexity → confidence threshold."""
    qhash = query_hash(query)
    ts = datetime.now(timezone.utc).isoformat()

    # Gate 1: PII detected → force local
    if pii_result.has_pii:
        entity_types = list({e.entity_type for e in pii_result.entities})
        return RoutingDecision(
            route=RouteType.LOCAL,
            reason=f"PII detected: {', '.join(entity_types)}",
            confidence=confidence,
            pii_detected=True,
            query_hash=qhash,
            timestamp=ts,
        )

    # Gate 2a: Force-local keyword pattern match (fast path, zero cost)
    matched_patterns = [p for p in ROUTING_FORCE_LOCAL_PATTERNS if re.search(p, query)]
    if matched_patterns:
        return RoutingDecision(
            route=RouteType.LOCAL,
            reason=f"Force-local pattern: {', '.join(matched_patterns)}",
            confidence=confidence,
            pii_detected=False,
            query_hash=qhash,
            timestamp=ts,
        )

    # Gate 2b: Cosine sensitivity (if keywords missed, vector available)
    if query_vector is not None:
        from core.safety.sensitivity import check_sovereign_similarity

        if check_sovereign_similarity(query_vector, query):
            return RoutingDecision(
                route=RouteType.LOCAL,
                reason="Cosine sensitivity gate: sovereign query detected",
                confidence=confidence,
                pii_detected=False,
                query_hash=qhash,
                timestamp=ts,
                cosine_gate_fired=True,
            )

    # Gate 2c: Complexity pre-scorer (pre-inference cloud routing)
    if complexity and complexity.get("skip_local"):
        signals = complexity.get("signals", [])
        penalty = complexity.get("penalty", 0)
        effective = (confidence.score - penalty) if confidence else (70.0 - penalty)
        if effective < ROUTING_CONFIDENCE_THRESHOLD:
            synth_conf = ConfidenceResult(
                score=effective,
                method="complexity_prescore",
                hedging_flags=signals,
            )
            return RoutingDecision(
                route=RouteType.CLOUD,
                reason=f"Complexity pre-score: {effective:.0f}% < {ROUTING_CONFIDENCE_THRESHOLD}% (signals: {', '.join(signals)})",
                confidence=synth_conf,
                pii_detected=False,
                query_hash=qhash,
                timestamp=ts,
            )

    # Gate 3: Confidence threshold
    if confidence is None:
        return RoutingDecision(
            route=RouteType.LOCAL,
            reason="No confidence score — defaulting to local",
            confidence=None,
            pii_detected=False,
            query_hash=qhash,
            timestamp=ts,
        )

    if confidence.score >= ROUTING_CONFIDENCE_THRESHOLD:
        return RoutingDecision(
            route=RouteType.LOCAL,
            reason=f"Confidence {confidence.score}% >= {ROUTING_CONFIDENCE_THRESHOLD}%",
            confidence=confidence,
            pii_detected=False,
            query_hash=qhash,
            timestamp=ts,
        )

    return RoutingDecision(
        route=RouteType.CLOUD,
        reason=f"Confidence {confidence.score}% < {ROUTING_CONFIDENCE_THRESHOLD}%",
        confidence=confidence,
        pii_detected=False,
        query_hash=qhash,
        timestamp=ts,
    )


def log_routing_decision(decision: RoutingDecision) -> None:
    """Append routing decision to JSONL log (SYNTH schema)."""
    ROUTING_LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_file = ROUTING_LOG_DIR / f"{datetime.now(timezone.utc).strftime('%Y-%m-%d')}.jsonl"

    entry = {
        "timestamp": decision.timestamp,
        "query_hash": decision.query_hash,
        "confidence_score": decision.confidence.score if decision.confidence else None,
        "route_taken": decision.route.value,
        "pii_detected": decision.pii_detected,
        "reason": decision.reason,
        "user_accepted": None,  # Populated by feedback loop (Phase 5.2)
    }

    with open(log_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def backfill_user_accepted(query_hash_value: str, accepted: bool | None) -> bool:
    """Update the most recent routing log entry matching query_hash with user feedback.

    Returns True if a matching entry was found and updated.
    accepted: True (accept), False (reject), None (skip).
    """
    ROUTING_LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_file = ROUTING_LOG_DIR / f"{datetime.now(timezone.utc).strftime('%Y-%m-%d')}.jsonl"

    if not log_file.exists():
        return False

    lines = log_file.read_text(encoding="utf-8").strip().split("\n")
    updated = False

    # Scan in reverse to find the most recent matching entry
    for i in range(len(lines) - 1, -1, -1):
        try:
            entry = json.loads(lines[i])
        except json.JSONDecodeError:
            continue
        if entry.get("query_hash") == query_hash_value and entry.get("user_accepted") is None:
            entry["user_accepted"] = accepted
            lines[i] = json.dumps(entry)
            updated = True
            break

    if updated:
        log_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

    return updated
