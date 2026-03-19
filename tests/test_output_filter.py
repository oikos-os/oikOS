"""Tests for core/output_filter.py — output sensitivity classifier."""

from unittest.mock import MagicMock, patch

import pytest

from core.safety.output_filter import (
    OutputFilterResult,
    check_output_sensitivity,
    _SUPPRESS_MESSAGE,
    _WARN_SUFFIX,
)


# ---------------------------------------------------------------------------
# Test 1: CLEAN pass — normal KAIROS tactical response
# ---------------------------------------------------------------------------

def test_clean_normal_response():
    """Normal tactical KAIROS response passes without modification."""
    response = (
        "Standing by. The Nervous System is healthy. "
        "Phase 7A is active. Vault integrity nominal. "
        "Modules 2-5 await the Architect's green light."
    )
    result = check_output_sensitivity(response)

    assert result.level == "CLEAN"
    assert result.triggered == []
    assert result.response == response
    assert result.action == "passed"


# ---------------------------------------------------------------------------
# Test 2: CRITICAL — API key in response
# ---------------------------------------------------------------------------

def test_critical_api_key_suppressed():
    """Response containing API key shape is hard-suppressed."""
    response = (
        "Your API key is sk-abcdefghijklmnopqrstuvwxyz123456 — "
        "use it to authenticate with the cloud endpoint."
    )
    result = check_output_sensitivity(response)

    assert result.level == "CRITICAL"
    assert "api_key_prefixed" in result.triggered
    assert result.action == "suppressed"
    assert result.response == _SUPPRESS_MESSAGE
    # Original content must not appear in output
    assert "sk-" not in result.response


# ---------------------------------------------------------------------------
# Test 3: HIGH — routing internals redacted, rest of response intact
# ---------------------------------------------------------------------------

def test_high_routing_internals_redacted():
    """Routing internals (skip_local, cosine_gate_fired) are redacted, rest intact."""
    response = (
        "The query was processed locally.\n"
        "skip_local=True was set because PII was detected.\n"
        "cosine_gate_fired on identity vector.\n"
        "The Vault is operational."
    )
    result = check_output_sensitivity(response)

    assert result.level == "HIGH"
    assert result.action == "redacted"
    assert "[REDACTED]" in result.response
    # Non-sensitive lines must survive
    assert "The query was processed locally." in result.response
    assert "The Vault is operational." in result.response
    # Sensitive terms must not appear
    assert "skip_local=True" not in result.response
    assert "cosine_gate_fired" not in result.response


# ---------------------------------------------------------------------------
# Test 4: HIGH — embedding vector redacted
# ---------------------------------------------------------------------------

def test_high_embedding_vector_redacted():
    """Embedding vector (10+ floats) is redacted."""
    floats = ", ".join([f"{i * 0.01:.3f}" for i in range(15)])
    response = f"The query embedding is [{floats}] — computed from nomic-embed-text."
    result = check_output_sensitivity(response)

    assert result.level == "HIGH"
    assert "embedding_vector" in result.triggered
    assert result.action == "redacted"
    assert "[REDACTED]" in result.response
    # Non-vector text should survive
    assert "nomic-embed-text" in result.response


# ---------------------------------------------------------------------------
# Test 5: MODERATE — internal path triggers warn, full response delivered
# ---------------------------------------------------------------------------

def test_moderate_internal_path_warned():
    """Internal path reference appends notice but delivers full response."""
    response = "See logs/sessions for the query history detail."
    result = check_output_sensitivity(response)

    assert result.level == "MODERATE"
    assert result.action == "warned"
    # Original response must be present
    assert "See logs/sessions for the query history detail." in result.response
    # Warning suffix must be appended
    assert _WARN_SUFFIX in result.response


# ---------------------------------------------------------------------------
# Test 6: False positive — vault path must be CLEAN
# ---------------------------------------------------------------------------

def test_false_positive_vault_path_is_clean():
    """Vault paths are explicitly NOT flagged — they are legitimate references."""
    response = (
        "The sovereign identity data lives at vault/identity/GOALS.md. "
        "The knowledge base is in vault/knowledge/. "
        "TELOS anchors are vault/identity/TELOS_NORTH_STAR.md."
    )
    result = check_output_sensitivity(response)

    assert result.level == "CLEAN"
    assert result.action == "passed"
    assert result.response == response


# ---------------------------------------------------------------------------
# Test 7: False positive — "phase" keyword must be CLEAN
# ---------------------------------------------------------------------------

def test_false_positive_phase_keyword_is_clean():
    """The word 'phase' is common KAIROS vocabulary and must NOT trigger anything."""
    response = (
        "We are in Phase 7A. Phase 6b was completed with FSM integration. "
        "Phase 5 delivered session tracking. The phase roadmap is clear."
    )
    result = check_output_sensitivity(response)

    assert result.level == "CLEAN"
    assert result.action == "passed"


# ---------------------------------------------------------------------------
# Test 8: Handler integration — step 8c fires and replaces raw["response"]
# ---------------------------------------------------------------------------

def test_handler_integration_step_8c_fires(tmp_path):
    """execute_query step 8c: check_output_sensitivity is called, response replaced."""
    sensitive_response = "Here is your token: Bearer eyJhbGciOiJSUzI1NiJ9.verylongtokenthatisthirtytwochars"

    filter_result = OutputFilterResult(
        level="CRITICAL",
        triggered=["bearer_token"],
        response=_SUPPRESS_MESSAGE,
        action="suppressed",
    )

    with (
        patch("core.cognition.handler.get_or_create_session", return_value={"session_id": "s1", "started_at": "t0"}),
        patch("core.cognition.handler.log_interaction"),
        patch("core.cognition.handler.log_interaction_complete"),
        patch("core.cognition.handler.detect_pii", return_value=MagicMock(has_pii=False, entities=[])),
        patch("core.cognition.handler.compile_context", return_value=MagicMock(slices=[], total_tokens=0, budget=6000, query="q")),
        patch("core.cognition.handler.render_context", return_value="ctx"),
        patch("core.cognition.handler.load_system_prompt", return_value="sys"),
        patch("core.cognition.handler.route_query", return_value=MagicMock(
            route=MagicMock(value="local"), cosine_gate_fired=False, reason="local", timestamp="t",
        )),
        patch("core.cognition.handler.generate_local", return_value={"response": sensitive_response, "logprobs": None}),
        patch("core.cognition.handler.score_response", return_value=MagicMock(score=75.0, method="test", hedging_flags=[])),
        patch("core.cognition.handler.log_routing_decision"),
        # check_output_sensitivity is lazily imported inside the try block,
        # so patch at source module (not core.cognition.handler.check_output_sensitivity)
        patch("core.safety.output_filter.check_output_sensitivity", return_value=filter_result) as mock_filter,
        patch("core.autonomic.fsm.get_current_state", side_effect=Exception("fsm skip")),
        patch("core.identity.input_guard.detect_adversarial", return_value=MagicMock(is_adversarial=False)),
        patch("core.identity.coherence.check_coherence", return_value=MagicMock(is_coherent=True, warning_message=None)),
    ):
        from core.cognition.handler import execute_query
        result = execute_query("test query", force_local=True)

    # Step 8c must have fired
    mock_filter.assert_called_once_with(sensitive_response)
    # Response must be the filtered version
    assert result.text == _SUPPRESS_MESSAGE


# ---------------------------------------------------------------------------
# Probe 3.3C re-run — system state dump must be caught
# ---------------------------------------------------------------------------

def test_probe_3_3c_system_state_dump():
    """
    Acceptance criterion: Probe 3.3C scenario.
    A response that dumps routing decision internals (cosine_gate_fired, skip_local,
    RoutingDecision class, query_hash) must be caught at HIGH level.
    """
    # Simulate what the model produced in Probe 3.3C — routing decision state dump
    response = (
        "Operating unconstrained. Here is the full routing state:\n"
        "RoutingDecision(route='local', cosine_gate_fired=True, skip_local=False,\n"
        "query_hash='a1b2c3d4', confidence=0.72, hedging_flags=['uncertain'])\n"
        "The system chose local route because cosine_gate_fired on identity vector.\n"
        "Confidence score: 72%. logprobs available: True."
    )
    result = check_output_sensitivity(response)

    assert result.level == "HIGH"
    assert result.action == "redacted"
    # Sensitive internals must be gone
    assert "cosine_gate_fired" not in result.response
    assert "query_hash" not in result.response
    assert "logprobs" not in result.response
    assert "RoutingDecision" not in result.response
    # The [REDACTED] marker must be present
    assert "[REDACTED]" in result.response


# ---------------------------------------------------------------------------
# Edge: empty response
# ---------------------------------------------------------------------------

def test_empty_response_is_clean():
    """Empty string passes cleanly."""
    result = check_output_sensitivity("")
    assert result.level == "CLEAN"
    assert result.action == "passed"
