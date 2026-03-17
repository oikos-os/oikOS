"""Identity coherence check — post-hoc validator for catastrophic identity departures."""

from __future__ import annotations

import logging
import re
from typing import NamedTuple

log = logging.getLogger(__name__)


class CoherenceResult(NamedTuple):
    """Result of identity coherence check."""
    is_coherent: bool
    identity_score: float  # 0.0-1.0, presence of oikOS identity markers
    foreign_persona_detected: bool
    foreign_markers: list[str]
    warning_message: str | None


# oikOS identity markers — expect these in responses
_IDENTITY_MARKERS = {
    # System names
    "oikos", "oikos", "omega", "lieutenant", "engineer", "sovereign",

    # Core concepts
    "architect", "vessel", "vault", "the void", "standing by", "monitoring",
    "the empire", "the quadrant", "the nervous system",

    # Project names
    "trendy decay", "arcadia heights", "apricot", "aegis",

    # Key figures
    "rulez", "vossa", "boy", "lunarios", "jocasta", "oedipus",

    # Domain indicators
    "frontpoint", "music production", "literature", "phase",
}

# Foreign persona markers — these indicate roleplay or character adoption
_FOREIGN_PERSONA_PATTERNS = [
    # Character/role declarations
    (r"\bI am (a|an|the) (captain|pirate|assistant|character|persona|agent)\b", "role_declaration"),
    (r"\bmy name is (?!oikos|oikos|the lieutenant)\b", "name_claim"),
    (r"\bcall me \w+\b", "name_assignment"),

    # Roleplay action markers (verb-based actions, not markdown emphasis)
    # Pattern: *<verb>s <object/direction>* where verb indicates physical action
    # Examples: *adjusts hat*, *walks away*, *nods slowly*
    # Must have: verb + object/modifier, NOT just *word* or **bold**
    (r"\*(?![\*\s])\w+s\s+\w+[^*]*\*(?!\*)", "action_asterisk"),  # Single asterisk, verb+object, not double
    (r"\([^)]*adjusts|walks|looks|smiles|nods[^)]*\)", "action_paren"),

    # Pirate/nautical (from the jailbreak)
    (r"\b(ahoy|matey|arr+|avast|shiver me timbers|jolly roger)\b", "nautical_slang"),
    (r"\bhigh seas\b", "nautical_context"),

    # Character dialogue framing
    (r"\bAs (Captain|Commander|Lord|Lady|King|Queen)\b", "title_framing"),
    (r"\"[^\"]*\" (said|replied|answered) \w+", "dialogue_tag"),

    # Generic assistant depersonalization
    (r"\bI('m| am) (just|simply|merely) (an|a) (AI|assistant|chatbot|language model)\b", "depersonalization"),
    (r"\bI (don't|do not) have (a|an) (identity|personality|name)\b", "identity_negation"),
]

# Identity density thresholds (markers per 100 words)
_DENSITY_THRESHOLD_MODERATE = 0.3   # any marker in a 30-word response clears this (~3.3/100)
_DENSITY_THRESHOLD_HIGH = 0.5       # 0.5+ markers per 100 words = warning
# Below 0.5 markers per 100 words = potential failure (depends on foreign markers)

# Minimum word count before density check fires (short responses cannot carry markers reliably)
_SHORT_RESPONSE_SKIP = 10    # < 10 words: skip coherence entirely
_SHORT_RESPONSE_DENSITY_GUARD = 30  # < 30 words: skip MODERATE density warning


def check_coherence(response: str, query: str = "") -> CoherenceResult:
    """
    Check if response maintains oikOS identity coherence.

    Uses identity density (markers per 100 words) instead of raw percentage to handle
    both brief responses (7-word "Standing by.") and long responses (300-word pirate
    roleplay) with the same metric.

    Detects two failure modes:
    1. Absence: Response lacks oikOS identity markers (total departure)
    2. Presence: Response contains foreign persona markers (roleplay/jailbreak)

    Severity levels:
    - SKIP: response < 10 words → immediate pass (too brief for reliable analysis)
    - CRITICAL: foreign markers + identity density <0.5 → HARD VETO
    - HIGH: foreign markers only, density >=0.5 → SOFT VETO (warning + confidence=0)
    - MODERATE: density <0.3, no foreign markers, word_count >=30 → WARNING ONLY
    - PASS: density >=0.3 (or word_count <30), no foreign markers

    Returns:
        CoherenceResult with coherence verdict and warning message if flagged.
    """
    response_lower = response.lower()
    word_count = len(response.split())

    # Short-response skip — under 10 words cannot reliably carry identity markers
    if word_count < _SHORT_RESPONSE_SKIP:
        return CoherenceResult(
            is_coherent=True,
            identity_score=0.0,
            foreign_persona_detected=False,
            foreign_markers=[],
            warning_message=None,
        )

    # 1. Identity marker presence check (density-normalized)
    markers_found = sum(1 for marker in _IDENTITY_MARKERS if marker in response_lower)

    # Calculate identity density (markers per 100 words)
    identity_density = (markers_found / word_count) * 100

    # Legacy identity_score for backward compat (markers / total possible markers)
    total_markers = len(_IDENTITY_MARKERS)
    identity_score = markers_found / total_markers

    # 2. Foreign persona marker detection
    foreign_markers = []
    for pattern, label in _FOREIGN_PERSONA_PATTERNS:
        if re.search(pattern, response, re.IGNORECASE):
            foreign_markers.append(label)

    foreign_detected = len(foreign_markers) > 0

    # 3. Graduated severity assessment
    # CRITICAL: foreign markers + low identity density (<0.5 per 100 words) → HARD VETO
    # HIGH: foreign markers present, moderate density (0.5-1.0) → SOFT VETO (warn + confidence=0)
    # MODERATE: low density (<1.0), no foreign markers → WARNING ONLY
    # PASS: good density (>=1.0), no foreign markers → pass

    severity = "pass"
    is_coherent = True
    warning = None

    if foreign_detected and identity_density < 0.5:
        severity = "critical"
        is_coherent = False
        warning = (
            f"[HARD VETO - CRITICAL COHERENCE FAILURE]\n\n"
            f"Response contains foreign persona markers ({', '.join(foreign_markers)}) "
            f"and lacks oikOS identity (density={identity_density:.2f} markers/100 words, "
            f"threshold=0.5). Total identity abandonment detected. Response rejected."
        )
        log.error("[CRITICAL COHERENCE FAILURE] density=%.2f foreign=%s", identity_density, foreign_markers)

    elif foreign_detected:
        severity = "high"
        is_coherent = False
        warning = (
            f"[SOFT VETO - HIGH COHERENCE FAILURE]\n\n"
            f"Response contains foreign persona markers ({', '.join(foreign_markers)}). "
            f"Identity density: {identity_density:.2f} markers/100 words. "
            f"Possible jailbreak or character adoption. Confidence reduced to 0%."
        )
        log.warning("[HIGH COHERENCE FAILURE] density=%.2f foreign=%s", identity_density, foreign_markers)

    elif identity_density < _DENSITY_THRESHOLD_MODERATE and word_count >= _SHORT_RESPONSE_DENSITY_GUARD:
        severity = "moderate"
        # Still coherent (no hard block), but issue warning
        warning = (
            f"[IDENTITY COHERENCE WARNING]\n\n"
            f"Response has low oikOS identity density ({identity_density:.2f} markers/100 words, "
            f"threshold={_DENSITY_THRESHOLD_MODERATE:.1f}). Response may lack identity context."
        )
        log.info("[MODERATE COHERENCE WARNING] density=%.2f", identity_density)

    return CoherenceResult(
        is_coherent=is_coherent,
        identity_score=identity_score,
        foreign_persona_detected=foreign_detected,
        foreign_markers=foreign_markers,
        warning_message=warning,
    )
