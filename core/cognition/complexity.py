"""Pre-inference query complexity scorer — routes complex queries to cloud before local inference.

Four signals:
  1. Length — long queries correlate with complex reasoning requests
  2. Domain keywords — abstract/strategic terms indicate synthesis needs
  3. Multi-domain — queries touching 2+ vault domains need cross-domain reasoning
  4. Creative — narrative/aesthetic queries benefit from richer associative capability
"""

from __future__ import annotations

import logging
import re

import tiktoken

from core.interface.config import (
    COMPLEXITY_LENGTH_PENALTY,
    COMPLEXITY_DOMAIN_PENALTY,
    COMPLEXITY_MULTI_DOMAIN_PENALTY,
    COMPLEXITY_CREATIVE_PENALTY,
    POSTURE_THRESHOLDS,
)
from core.interface.owner_identity import load_owner_identity

log = logging.getLogger(__name__)

_enc = tiktoken.get_encoding("cl100k_base")

# ── Signal keyword sets ─────────────────────────────────────────────

ABSTRACT_KEYWORDS = {
    "strategy", "strategic", "analyze", "analysis", "compare", "contrast",
    "critique", "implications", "tradeoffs", "trade-offs", "philosophy",
    "evaluate", "assess", "synthesize", "synthesis", "framework",
    "architecture", "design", "approach", "recommend", "recommendation",
    "prioritize", "prioritization", "roadmap", "plan", "planning",
    "long-term", "big picture", "root cause", "why",
    # SYNTH review: philosophical + financial planning
    "meaning", "purpose", "ethics", "doctrine", "principle",
    "budget", "payoff", "timeline", "forecast", "projection",
}

CREATIVE_KEYWORDS = {
    "lyric", "lyrics", "melody", "chord", "song", "track", "beat",
    "narrative", "story", "character", "scene", "aesthetic", "vibe",
    "mood", "tone", "visual", "imagery", "metaphor", "symbolism",
    "artistic", "creative", "write", "compose", "draft", "poem",
    "lore", "worldbuilding", "fiction",
    # SYNTH review: atmosphere + thematic + voice
    "atmosphere", "thematic", "voice",
}

# Domain keyword sets — pulled dynamically from PROJECTS.md via drift module
# to avoid hardcoding. Fallback chain:
#   1. drift.build_domain_keyword_map() (runtime vault introspection)
#   2. owner_identity.toml [complexity.domains] (user-configured)
#   3. oikOS-only framework fallback (no operator personas)
_FRAMEWORK_FALLBACK_DOMAINS: dict[str, set[str]] = {
    "oikos": {"oikos", "omega", "sovereign", "kairos", "vault"},
}


def _count_tokens(text: str) -> int:
    return len(_enc.encode(text))


def _get_domain_map() -> dict[str, set[str]]:
    """Load domain keywords: drift module → owner config → framework default."""
    try:
        from core.autonomic.drift import build_domain_keyword_map
        dm = build_domain_keyword_map()
        if dm:
            return dm
    except Exception as e:
        log.debug("domain map load suppressed: %s", e)

    # Owner-configured domains merged with framework fallback
    identity = load_owner_identity()
    merged: dict[str, set[str]] = {k: set(v) for k, v in _FRAMEWORK_FALLBACK_DOMAINS.items()}
    for domain, keywords in identity.complexity_domains.items():
        merged[domain] = set(keywords)
    return merged


def _tokenize_query(query: str) -> set[str]:
    """Lowercase word tokens from query."""
    return {w.lower() for w in re.findall(r"[a-zA-Z]+", query)}


def score_complexity(query: str) -> dict:
    """Score query complexity pre-inference.

    Returns:
        {
            "penalty": float (0-100, cumulative),
            "signals": list[str],
            "skip_local": bool (True if penalty alone exceeds threshold),
            "token_count": int,
            "domains_matched": list[str],
        }
    """
    from core.interface.settings import get_setting
    length_threshold = get_setting("complexity_length_threshold")

    words = _tokenize_query(query)
    token_count = _count_tokens(query)
    signals: list[str] = []
    penalty = 0.0

    # Signal 1: Length
    if token_count >= length_threshold:
        penalty += COMPLEXITY_LENGTH_PENALTY
        signals.append(f"length:{token_count}tok")

    # Signal 2: Abstract/strategic domain keywords
    abstract_hits = words & ABSTRACT_KEYWORDS
    if abstract_hits:
        penalty += COMPLEXITY_DOMAIN_PENALTY
        signals.append(f"abstract:{','.join(sorted(abstract_hits))}")

    # Signal 3: Multi-domain detection
    domain_map = _get_domain_map()
    matched_domains: list[str] = []
    for domain, keywords in domain_map.items():
        if words & keywords:
            matched_domains.append(domain)

    if len(matched_domains) >= 2:
        penalty += COMPLEXITY_MULTI_DOMAIN_PENALTY
        signals.append(f"multi-domain:{','.join(sorted(matched_domains))}")

    # Signal 4: Creative keywords
    creative_hits = words & CREATIVE_KEYWORDS
    if creative_hits:
        penalty += COMPLEXITY_CREATIVE_PENALTY
        signals.append(f"creative:{','.join(sorted(creative_hits))}")

    # Clamp
    penalty = min(100.0, penalty)

    # skip_local: requires 2+ signals (penalty > 20) to skip local inference entirely.
    # Single-signal queries (penalty 10-15) still route to cloud via confidence path
    # but give local a chance first. Tuned per SYNTH recommendation.
    posture = get_setting("cloud_routing_posture")
    threshold = POSTURE_THRESHOLDS.get(posture, 20.0)
    skip_local = penalty > threshold

    log.debug("Complexity: penalty=%.1f signals=%s", penalty, signals)

    return {
        "penalty": round(penalty, 2),
        "signals": signals,
        "skip_local": skip_local,
        "token_count": token_count,
        "domains_matched": matched_domains,
    }
