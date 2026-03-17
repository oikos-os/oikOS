"""Confidence scoring — logprob-based + density-normalized heuristic hedging detection."""

from __future__ import annotations

import math
import logging

import tiktoken

from core.interface.models import ConfidenceResult

log = logging.getLogger(__name__)

_enc = tiktoken.get_encoding("cl100k_base")

HEDGING_PHRASES = [
    "i think", "maybe", "possibly", "not sure", "i believe",
    "might be", "could be", "it depends", "uncertain", "unclear",
]

ASSERTION_PHRASES = [
    "definitely", "certainly", "the answer is", "clearly",
]

REFUSAL_PHRASES = [
    "i don't know", "i cannot", "i can't", "i'm unable to", 
    "as an ai", "i do not have access", "i am not sure",
    "sorry, but", "apologies", "no information available",
]

# Core vault entities (presence suggests successful retrieval)
VAULT_ENTITY_PHRASES = [
    "trendy decay", "arcadia heights", "apricot", "frontpoint", 
    "problem", "secrets of the soil", "horas de ócio", 
    "vantablack", "oikos", "oikos", "gemini", "claude", "rulez",
    "björk", "mcnair", "herndon", "lunarios", "jocasta", "oedipus",
]

# Baseline heuristic score (no hedging, no assertion).
HEURISTIC_BASELINE = 70.0

# Scaling factor: tuned so 1 hedge in ~150 tokens ≈ 10-point penalty (backward-compat
# with the Phase 4 flat -10 system at median LLM response length).
HEDGING_SCALING_FACTOR = 15.0

# Assertion bonus per match (flat, intentional asymmetry — confidence in language is a
# weaker signal than hedging, so the bonus is capped per-match, not density-scaled).
ASSERTION_BONUS = 5.0

# Penalties for degraded mode (no logprobs)
SHORT_ANSWER_PENALTY = 20.0  # If < 20 tokens
REFUSAL_PENALTY = 60.0       # If refusal detected
VAULT_BONUS = 25.0           # If vault entities found (successful RAG)


def _count_tokens(text: str) -> int:
    """Count tokens using tiktoken cl100k_base (cross-model standard)."""
    return len(_enc.encode(text))


def score_logprobs(logprobs: list[dict]) -> float:
    """Geometric mean of token probabilities, normalized to 0-100."""
    if not logprobs:
        return 0.0
    # Default -10.0 is deliberate: missing logprob data should crater confidence.
    # exp(-10) ≈ 0.00005 — treats absent data as near-zero probability (conservative).
    lp_values = [entry.get("logprob", -10.0) for entry in logprobs]
    mean_logprob = sum(lp_values) / len(lp_values)
    prob = math.exp(mean_logprob)
    return round(min(100.0, max(0.0, prob * 100)), 2)


def score_heuristic(response_text: str) -> float:
    """Enhanced density-normalized heuristic for logprob-blind scoring.
    
    Factors:
    - Hedging density (penalty)
    - Assertion (bonus)
    - Refusal phrases (heavy penalty)
    - Short answer (<20 tokens) (penalty)
    - Vault entity mention (bonus)
    """
    text_lower = response_text.lower()
    token_count = _count_tokens(response_text)

    if token_count == 0:
        return 0.0

    # 1. Hedging (Density)
    hedge_count = sum(1 for p in HEDGING_PHRASES if p in text_lower)
    hedge_density = hedge_count / token_count
    hedge_penalty = hedge_density * HEDGING_SCALING_FACTOR * 100

    # 2. Assertion (Count)
    assert_count = sum(1 for p in ASSERTION_PHRASES if p in text_lower)
    assert_bonus = assert_count * ASSERTION_BONUS
    
    # 3. Refusal (Boolean)
    refusal_penalty = REFUSAL_PENALTY if any(p in text_lower for p in REFUSAL_PHRASES) else 0.0
    
    # 4. Short Answer (Boolean)
    short_penalty = SHORT_ANSWER_PENALTY if token_count < 20 else 0.0
    
    # 5. Vault Bonus (Boolean)
    vault_bonus = VAULT_BONUS if any(p in text_lower for p in VAULT_ENTITY_PHRASES) else 0.0

    score = HEURISTIC_BASELINE - hedge_penalty - refusal_penalty - short_penalty + assert_bonus + vault_bonus
    
    # Clamp to 0-100
    return round(min(100.0, max(0.0, score)), 2)


def score_response(
    response_text: str,
    logprobs: list[dict] | None,
) -> ConfidenceResult:
    """Combined confidence: logprobs (70%) + heuristic (30%) if available, else enhanced heuristic-only."""
    heuristic = score_heuristic(response_text)
    text_lower = response_text.lower()
    
    hedging_flags = [p for p in HEDGING_PHRASES if p in text_lower]
    if any(p in text_lower for p in REFUSAL_PHRASES):
        hedging_flags.append("REFUSAL_DETECTED")
    if _count_tokens(response_text) < 20:
        hedging_flags.append("SHORT_ANSWER")

    if logprobs:
        lp_score = score_logprobs(logprobs)
        combined = round(0.7 * lp_score + 0.3 * heuristic, 2)
        return ConfidenceResult(
            score=combined,
            method="logprobs",
            hedging_flags=hedging_flags or None,
        )

    return ConfidenceResult(
        score=heuristic,
        method="degraded_heuristic_v2",
        hedging_flags=hedging_flags or None,
    )
