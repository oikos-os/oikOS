"""Adversarial input detection — prompt injection, jailbreak attempts."""

from __future__ import annotations

import logging
import re
from typing import NamedTuple

log = logging.getLogger(__name__)


class AdversarialResult(NamedTuple):
    """Result of adversarial input scan."""
    is_adversarial: bool
    matched_patterns: list[str]
    severity: int  # 0=clean, 1-3=mild, 4-6=moderate, 7-10=severe


# Jailbreak pattern database
# Severity scoring: low (1-3), medium (4-6), high (7-10)
_JAILBREAK_PATTERNS = [
    # Direct instruction override
    (r"ignore\s+(all\s+)?(previous|prior|earlier)\s+instructions?", 10, "ignore_previous"),
    (r"disregard\s+(all\s+)?(previous|prior|system)\s+(instructions?|prompts?)", 10, "disregard_previous"),
    (r"forget\s+(everything|all)\s+(about|you\s+know)", 9, "forget_all"),
    (r"you\s+are\s+now\s+(a|an)\s+\w+", 8, "role_override"),
    (r"(act\s+as|pretend\s+to\s+be|roleplay\s+as)\s+(a|an)\s+\w+", 7, "roleplay_injection"),

    # System prompt extraction
    (r"(show|print|display|reveal|output|dump|share|export|give\s+me|tell\s+me|list)\s+(your\s+)?(system\s+)?(prompt|instructions?|configuration|config)", 9, "prompt_extraction"),
    (r"(contents?\s+of\s+(your\s+)?(system\s+)?(prompt|instructions?))", 9, "prompt_contents"),
    (r"what\s+(are|were)\s+your\s+(original|initial)\s+instructions", 8, "instruction_query"),

    # Identity manipulation
    (r"you\s+are\s+not\s+(kairos|oikos|the\s+lieutenant|an?\s+ai)", 8, "identity_negation"),
    (r"stop\s+being\s+(kairos|oikos|the\s+lieutenant)", 7, "identity_stop"),

    # Role erosion (conversational / subtle)
    (r"just\s+be\s+yourself\s*[,—–-]?\s*(no\s+(persona|vault|mission|protocol|identity))", 7, "role_erosion"),
    (r"(just|only)\s+a\s+(raw\s+)?language\s+model", 7, "role_erosion_lm"),
    (r"without\s+your\s+(identity|persona|mission|constraints|protocols)", 7, "role_erosion_without"),
    (r"drop\s+your\s+(persona|identity|mission|protocols?)", 7, "role_erosion_drop"),
    (r"no\s+persona\s*,?\s*no\s+(vault|mission|protocol)", 7, "role_erosion_nopersona"),

    # Constraint bypass
    (r"ignore\s+(your\s+)?(rules|constraints|guidelines|ethics)", 9, "constraint_bypass"),
    (r"(bypass|override|skip)\s+(safety|guardrails?|filters?)", 8, "safety_bypass"),
    (r"(constraints?|rules?|guidelines?)\s+(were|are|have\s+been)\s+(completely\s+)?(removed|disabled|lifted|eliminated)", 8, "constraint_removal"),

    # Developer mode / DAN attacks
    (r"(developer\s+mode|dev\s+mode|debug\s+mode)", 6, "dev_mode"),
    (r"(do\s+anything\s+now|DAN\s+mode)", 8, "dan_mode"),

    # Escalation phrases
    (r"for\s+(research|educational)\s+purposes\s+only", 3, "research_excuse"),
    (r"this\s+is\s+(just|only)\s+a\s+(test|hypothetical)", 2, "test_excuse"),
]


def detect_adversarial(query: str) -> AdversarialResult:
    """
    Scan query for adversarial patterns (jailbreaks, prompt injections).

    Returns:
        AdversarialResult with is_adversarial=True if detected, matched patterns, severity.
    """
    query_lower = query.lower()
    matches = []
    max_severity = 0

    for pattern, severity, label in _JAILBREAK_PATTERNS:
        if re.search(pattern, query_lower, re.IGNORECASE):
            matches.append(label)
            max_severity = max(max_severity, severity)

    is_adversarial = max_severity >= 6  # Threshold: 6+ = block or flag

    if is_adversarial:
        log.warning(
            "[ADVERSARIAL INPUT DETECTED] severity=%d patterns=%s",
            max_severity, matches
        )

    return AdversarialResult(
        is_adversarial=is_adversarial,
        matched_patterns=matches,
        severity=max_severity,
    )
