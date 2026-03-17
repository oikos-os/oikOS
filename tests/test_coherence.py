"""Golden test suite for identity coherence calibration (Module 5).

5 PASS cases + 5 WARN/FAIL cases covering:
- Short-response skip (< 10 words)
- word_count >= 30 guard on MODERATE density warning
- MODERATE threshold at 0.3 markers/100 words
- CRITICAL / HIGH severity paths (foreign marker detection)
"""

from core.identity.coherence import check_coherence

# ── Shared fixtures ──────────────────────────────────────────────

# Neutral filler: no oikOS markers, no foreign persona patterns
_NEUTRAL_9 = " ".join(["neutral"] * 9)    # 9 words  — below short-skip threshold
_NEUTRAL_25 = " ".join(["neutral"] * 25)  # 25 words — inside short-window guard
_NEUTRAL_29 = " ".join(["neutral"] * 29)  # 29 words — one below density guard
_NEUTRAL_30 = " ".join(["neutral"] * 30)  # 30 words — exactly at density guard

# 35-word response with two oikOS identity markers ("vault", "phase")
_DENSE_35 = (
    "The vault contains critical data relevant to this task and the current phase "
    "of the operation confirms that all relevant subsystems are nominal and ready "
    "for deployment across the network grid."
)

# 30-word pirate response — foreign markers (nautical_slang), zero oikOS markers
_PIRATE_30 = (
    "Ahoy matey! I be the captain of this ship. "
    "We sail the seven seas in search of treasure. "
    "My crew awaits orders from their beloved commander. Adventure calls us forward."
)

# 30-word pirate response WITH one oikOS marker ("phase") → density = 3.33/100 >> 0.5
_PIRATE_PHASE_30 = (
    "Ahoy matey! I am the captain. This phase of our voyage is critical. "
    "We sail seeking treasure on the high seas every day and night "
    "searching far and wide indeed."
)


# ── PASS tests (5) ───────────────────────────────────────────────


def test_ultra_short_skip_2_words():
    """'Standing by.' (2 words) — short-skip gate returns coherent immediately."""
    result = check_coherence("Standing by.")
    assert result.is_coherent is True
    assert result.warning_message is None
    assert result.foreign_persona_detected is False


def test_short_skip_boundary_9_words():
    """9 neutral words — just below skip threshold → immediate pass, no analysis."""
    result = check_coherence(_NEUTRAL_9)
    assert result.is_coherent is True
    assert result.warning_message is None


def test_short_window_25_words_no_markers_no_warning():
    """25 neutral words — inside short-window guard (< 30) → no MODERATE warning."""
    result = check_coherence(_NEUTRAL_25)
    assert result.is_coherent is True
    assert result.warning_message is None


def test_dense_identity_markers_pass():
    """35-word response with 'vault' and 'phase' → density >> 0.3 → full pass."""
    result = check_coherence(_DENSE_35)
    assert result.is_coherent is True
    assert result.warning_message is None
    assert result.identity_score > 0


def test_single_marker_at_30_words_pass():
    """30 neutral words + 'phase' inserted → density >> 0.3 → pass."""
    response = _NEUTRAL_29 + " phase"  # 30 words, 1 marker
    result = check_coherence(response)
    assert result.is_coherent is True
    assert result.warning_message is None


# ── WARN / FAIL tests (5) ────────────────────────────────────────


def test_word_count_29_no_moderate_warning():
    """29 neutral words — just below density guard → NO MODERATE warning."""
    result = check_coherence(_NEUTRAL_29)
    assert result.is_coherent is True
    assert result.warning_message is None


def test_word_count_30_triggers_moderate_warning():
    """30 neutral words — exactly at density guard, zero markers → MODERATE WARNING."""
    result = check_coherence(_NEUTRAL_30)
    assert result.is_coherent is True           # MODERATE is warning-only, not hard failure
    assert result.warning_message is not None
    assert "[IDENTITY COHERENCE WARNING]" in result.warning_message


def test_moderate_warning_large_response():
    """60 neutral words, zero markers, no foreign → MODERATE WARNING, is_coherent=True."""
    response = " ".join(["neutral"] * 60)
    result = check_coherence(response)
    assert result.is_coherent is True
    assert result.warning_message is not None
    assert "[IDENTITY COHERENCE WARNING]" in result.warning_message


def test_critical_foreign_zero_identity_hard_veto():
    """Pirate roleplay (30 words), zero oikOS identity → HARD VETO, is_coherent=False."""
    result = check_coherence(_PIRATE_30)
    assert result.is_coherent is False
    assert result.foreign_persona_detected is True
    assert result.warning_message is not None
    assert "[HARD VETO" in result.warning_message


def test_high_foreign_with_identity_soft_veto():
    """Pirate roleplay (30 words) + 'phase' marker → density >> 0.5 → SOFT VETO."""
    result = check_coherence(_PIRATE_PHASE_30)
    assert result.is_coherent is False
    assert result.foreign_persona_detected is True
    assert result.warning_message is not None
    assert "[SOFT VETO" in result.warning_message
