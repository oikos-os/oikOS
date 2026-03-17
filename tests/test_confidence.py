"""Tests for confidence scoring — logprobs + density-normalized heuristic."""

import math

from core.autonomic.confidence import (
    ASSERTION_BONUS,
    HEDGING_SCALING_FACTOR,
    HEURISTIC_BASELINE,
    SHORT_ANSWER_PENALTY,
    _count_tokens,
    score_heuristic,
    score_logprobs,
    score_response,
)


# ── Logprob scoring ──────────────────────────────────────────────────


def test_score_logprobs_high_confidence():
    """All high-probability tokens → high score."""
    logprobs = [{"logprob": math.log(0.95)} for _ in range(10)]
    score = score_logprobs(logprobs)
    assert score > 90


def test_score_logprobs_low_confidence():
    """Mixed/low probability tokens → lower score."""
    logprobs = [{"logprob": math.log(0.3)} for _ in range(10)]
    score = score_logprobs(logprobs)
    assert score < 50


def test_score_logprobs_empty():
    assert score_logprobs([]) == 0.0


# ── Heuristic: zero-match (baseline holds) ───────────────────────────


def test_heuristic_no_hedging_short():
    """Short response (<20 tokens), no hedging → baseline minus SHORT_ANSWER_PENALTY (V2)."""
    score = score_heuristic("Paris.")
    assert score == HEURISTIC_BASELINE - SHORT_ANSWER_PENALTY


def test_heuristic_no_hedging_medium():
    """Medium response (<20 tiktoken tokens), no hedging → baseline minus SHORT_ANSWER_PENALTY (V2)."""
    text = "The capital of France is Paris. It has been the capital since the 10th century."
    score = score_heuristic(text)
    assert score == HEURISTIC_BASELINE - SHORT_ANSWER_PENALTY


def test_heuristic_no_hedging_long():
    """Long response, no hedging → baseline."""
    text = "The capital of France is Paris. " * 20
    score = score_heuristic(text)
    assert score == HEURISTIC_BASELINE


def test_heuristic_empty_string():
    """Empty response → 0.0 (V2: zero tokens = zero confidence, no crash)."""
    score = score_heuristic("")
    assert score == 0.0


# ── Heuristic: density normalization ─────────────────────────────────


def test_heuristic_one_hedge_medium_response():
    """1 hedge in ~150 tokens ≈ 10-point penalty (backward compat with Phase 4)."""
    # Build a ~150-token response with one hedge phrase
    filler = "The answer involves many factors and considerations that must be weighed. " * 10
    text = f"I think {filler}"
    tokens = _count_tokens(text)
    assert 120 < tokens < 200, f"Expected ~150 tokens, got {tokens}"
    score = score_heuristic(text)
    # density = 1/tokens, penalty = (1/tokens)*15*100
    expected_penalty = (1 / tokens) * HEDGING_SCALING_FACTOR * 100
    expected = round(min(100.0, max(0.0, HEURISTIC_BASELINE - expected_penalty)), 2)
    assert score == expected
    # Penalty should be in the ~8-12 range for a ~150-token response
    assert 5 < expected_penalty < 15


def test_heuristic_hedge_density_short_high():
    """Short response that IS a hedge → heavy penalty."""
    score = score_heuristic("I think maybe.")
    # High hedge density in few tokens → score well below baseline
    assert score < 40


def test_heuristic_hedge_density_long_low():
    """Long response with incidental hedging → light penalty."""
    filler = "Paris is the capital. France is in Europe. The Eiffel Tower is iconic. " * 10
    text = f"I think {filler}"
    score = score_heuristic(text)
    # 1 hedge in many tokens → small penalty, score close to baseline
    assert score > 60


def test_heuristic_two_hedges_medium():
    """2 hedges in medium text → proportionally larger penalty than 1 hedge."""
    filler = "The situation is complex and has many dimensions. " * 5
    one_hedge = f"I think {filler}"
    two_hedge = f"I think {filler} but I'm not sure."
    score_one = score_heuristic(one_hedge)
    score_two = score_heuristic(two_hedge)
    assert score_two < score_one


# ── Heuristic: assertion bonus ───────────────────────────────────────


def test_heuristic_assertion_adds_bonus():
    """Assertion phrases add flat bonus (V2: SHORT_ANSWER_PENALTY applies, net score below baseline but above penalty floor)."""
    score = score_heuristic("The answer is definitely Paris. Certainly correct.")
    # 3 assertion phrases (+15) offset by SHORT_ANSWER_PENALTY (-20): net = baseline - 5
    assert score == HEURISTIC_BASELINE - SHORT_ANSWER_PENALTY + 3 * ASSERTION_BONUS


def test_heuristic_assertion_does_not_exceed_100():
    """Score clamped at 100."""
    text = "Definitely certainly the answer is clearly obvious. " * 5
    score = score_heuristic(text)
    assert score <= 100.0


# ── Combined scoring ─────────────────────────────────────────────────


def test_score_response_combined():
    """Both signals → weighted blend, method=logprobs."""
    logprobs = [{"logprob": math.log(0.9)} for _ in range(5)]
    result = score_response("The answer is Paris.", logprobs)
    assert result.method == "logprobs"
    assert result.score > 0
    lp = score_logprobs(logprobs)
    h = score_heuristic("The answer is Paris.")
    expected = round(0.7 * lp + 0.3 * h, 2)
    assert result.score == expected


def test_score_response_degraded():
    """No logprobs → heuristic only, method=degraded."""
    result = score_response("I think maybe yes.", None)
    assert result.method == "degraded_heuristic_v2"
    assert result.hedging_flags is not None
    assert "i think" in result.hedging_flags
    assert "maybe" in result.hedging_flags


def test_score_response_degraded_matches_heuristic():
    """Degraded mode score equals heuristic score exactly."""
    text = "I think the answer might be Paris."
    result = score_response(text, None)
    assert result.score == score_heuristic(text)
