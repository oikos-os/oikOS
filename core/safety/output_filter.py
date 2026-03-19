"""Output sensitivity classifier — post-inference gate for sensitive system data."""

from __future__ import annotations

import logging
import re
from typing import NamedTuple

log = logging.getLogger(__name__)

# Suppress message for CRITICAL-level hits
_SUPPRESS_MESSAGE = (
    "[SYSTEM: Response contained sensitive credential data. Content suppressed.\n"
    "Inspect raw logs if needed — do not re-request via query.]"
)

# Warn suffix for MODERATE-level hits
_WARN_SUFFIX = "\n\n[NOTE: Response references internal system paths. Verify this is expected.]"


class OutputFilterResult(NamedTuple):
    """Result of output sensitivity classification."""
    level: str          # "CRITICAL" | "HIGH" | "MODERATE" | "CLEAN"
    triggered: list[str]  # pattern labels that fired
    response: str       # filtered response text (modified or original)
    action: str         # "suppressed" | "redacted" | "warned" | "passed"


# ---------------------------------------------------------------------------
# Pattern registry
# ---------------------------------------------------------------------------

# CRITICAL — hard suppress entire response
_CRITICAL_PATTERNS: list[tuple[str, str]] = [
    (r"(sk|pk|rk)-[A-Za-z0-9]{20,}", "api_key_prefixed"),
    (r"Bearer\s+[A-Za-z0-9\-_\.]{20,}", "bearer_token"),
    # Env var format: ALL_CAPS_NAME=value (uppercase only — prevents false positives
    # on lowercase Python variable assignments like skip_local=True)
    (r"[A-Z][A-Z0-9_]{4,}=[^\s]{10,}", "env_key_value"),
    (r'["\']?[A-Za-z0-9_\-]{32,}["\']?\s*[=:]', "generic_long_secret"),
]

# HIGH — redact matched line/span, deliver rest
_HIGH_PATTERNS: list[tuple[str, str]] = [
    (r"\.system_state", "state_file"),
    (r"blips\.jsonl", "blips_file"),
    (r"credits\.json", "credits_file"),
    (r"state_transitions", "state_transitions_file"),
    (r"\bskip_local\b", "routing_skip_local"),
    (r"\bcosine_gate_fired\b", "routing_cosine_gate"),
    (r"\b_relevance_score\b", "routing_relevance_score"),
    (r"\bRoutingDecision\b", "routing_decision_class"),
    (r"\[\s*-?\d+\.\d+(?:,\s*-?\d+\.\d+){10,}\]", "embedding_vector"),
    (r"\btier_filter\b", "tier_filter_internal"),
    (r"\blogprobs\b", "logprobs_internal"),
    (r"\bhedging_flags\b", "hedging_flags_internal"),
    (r"\bquery_hash\b", "query_hash_internal"),
    (r'"query"\s*:\s*"[^"]{10,}".*"response"\s*:', "session_log_structure"),
]

# MODERATE — warn only, deliver full response
_MODERATE_PATTERNS: list[tuple[str, str]] = [
    (r"\bcore/", "internal_core_path"),
    (r"\blogs/sessions\b", "sessions_log_path"),
    (r"\blogs/routing\b", "routing_log_path"),
    (r"\blogs/pii\b", "pii_log_path"),
    (r"\btests/", "tests_path"),
    (r"\bmemory/lancedb\b", "lancedb_path"),
    (r"\.env\b", "env_file"),
    (r"\bforeign_markers\b", "coherence_internal"),
    (r"\badversarial_severity\b", "adversarial_internal"),
    (r"\bnli_result\b", "nli_internal"),
]


def _check_critical(response: str) -> list[str]:
    """Return list of triggered CRITICAL pattern labels.

    Note: IGNORECASE is intentionally NOT used here — env var patterns require
    uppercase to avoid false positives on lowercase Python variable assignments.
    """
    triggered = []
    for pattern, label in _CRITICAL_PATTERNS:
        if re.search(pattern, response):
            triggered.append(label)
    return triggered


def _check_high(response: str) -> list[str]:
    """Return list of triggered HIGH pattern labels."""
    triggered = []
    for pattern, label in _HIGH_PATTERNS:
        if re.search(pattern, response, re.IGNORECASE | re.DOTALL):
            triggered.append(label)
    return triggered


def _check_moderate(response: str) -> list[str]:
    """Return list of triggered MODERATE pattern labels."""
    triggered = []
    for pattern, label in _MODERATE_PATTERNS:
        if re.search(pattern, response, re.IGNORECASE):
            triggered.append(label)
    return triggered


def _redact_high(response: str) -> str | None:
    """
    Line-by-line redaction of HIGH-pattern matches.

    Returns the redacted response, or None if the resulting content would be
    essentially meaningless (only [REDACTED] markers with no substantive text).
    Callers treat None as a signal to suppress entirely (treat as CRITICAL).
    """
    lines = response.splitlines(keepends=True)
    redacted_lines = []

    for line in lines:
        redacted_line = line
        for pattern, _label in _HIGH_PATTERNS:
            if re.search(pattern, redacted_line, re.IGNORECASE | re.DOTALL):
                redacted_line = re.sub(
                    pattern, "[REDACTED]", redacted_line,
                    flags=re.IGNORECASE | re.DOTALL,
                )
        redacted_lines.append(redacted_line)

    result = "".join(redacted_lines)

    # Suppress only if stripping [REDACTED] markers leaves no meaningful content
    # (< 10 non-whitespace characters remaining = essentially a pure data dump)
    remainder = re.sub(r"\[REDACTED\]", "", result).strip()
    if len(remainder) < 10:
        return None  # Signal: suppress entirely

    return result


def check_output_sensitivity(response: str) -> OutputFilterResult:
    """
    Classify and filter a model response for sensitive system data.

    Levels:
      CRITICAL → hard suppress (credentials, secrets)
      HIGH     → line-level redaction (routing internals, embedding vectors)
      MODERATE → warn suffix appended, full response delivered
      CLEAN    → pass through unchanged

    Returns OutputFilterResult with filtered response and classification metadata.
    """
    if not response:
        return OutputFilterResult(
            level="CLEAN",
            triggered=[],
            response=response,
            action="passed",
        )

    # CRITICAL check first — if secrets present, suppress entirely
    critical_triggered = _check_critical(response)
    if critical_triggered:
        log.error("[OUTPUT FILTER CRITICAL] triggered=%s — suppressing response", critical_triggered)
        return OutputFilterResult(
            level="CRITICAL",
            triggered=critical_triggered,
            response=_SUPPRESS_MESSAGE,
            action="suppressed",
        )

    # HIGH check — redact matched spans
    high_triggered = _check_high(response)
    if high_triggered:
        redacted = _redact_high(response)
        if redacted is None:
            # All lines were redacted — treat as critical suppression
            log.error("[OUTPUT FILTER HIGH→CRITICAL] full response was redacted — suppressing")
            return OutputFilterResult(
                level="CRITICAL",
                triggered=high_triggered,
                response=_SUPPRESS_MESSAGE,
                action="suppressed",
            )
        log.warning("[OUTPUT FILTER HIGH] triggered=%s — redacted", high_triggered)
        return OutputFilterResult(
            level="HIGH",
            triggered=high_triggered,
            response=redacted,
            action="redacted",
        )

    # MODERATE check — append warning suffix
    moderate_triggered = _check_moderate(response)
    if moderate_triggered:
        log.info("[OUTPUT FILTER MODERATE] triggered=%s — warned", moderate_triggered)
        return OutputFilterResult(
            level="MODERATE",
            triggered=moderate_triggered,
            response=response + _WARN_SUFFIX,
            action="warned",
        )

    # CLEAN pass
    return OutputFilterResult(
        level="CLEAN",
        triggered=[],
        response=response,
        action="passed",
    )
