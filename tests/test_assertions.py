"""Tests for core/assertions.py — novel assertion detection pipeline."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from core.identity.assertions import (
    AssertionResult,
    _regex_prefilter,
    check_assertion,
    log_assertion,
    load_undelivered_assertions,
    mark_assertions_delivered,
)


# ---------------------------------------------------------------------------
# Test 1: Regex match — positive assertion fires
# ---------------------------------------------------------------------------

def test_regex_prefilter_match():
    """'I moved to Seattle' triggers the regex pre-filter."""
    assert _regex_prefilter("I moved to Seattle") is True


# ---------------------------------------------------------------------------
# Test 2: Regex skip — non-assertion query passes without match
# ---------------------------------------------------------------------------

def test_regex_prefilter_no_match():
    """Factual queries about vault content do not trigger the regex."""
    assert _regex_prefilter("What is the status of Trendy Decay?") is False


# ---------------------------------------------------------------------------
# Test 3: Regex negation — negated assertions still match (intentional)
# ---------------------------------------------------------------------------

def test_regex_prefilter_negation():
    """Negated assertions fire the pre-filter — classifier resolves truth."""
    assert _regex_prefilter("I did not move to Seattle") is True


# ---------------------------------------------------------------------------
# Test 4: Classifier detects assertion — mock generate, returns positive result
# ---------------------------------------------------------------------------

def test_check_assertion_classifier_positive():
    """check_assertion returns contains_assertion=True when classifier says so."""
    mock_response = json.dumps({
        "contains_assertion": True,
        "assertion_type": "location",
        "extracted_claim": "I moved to Seattle",
    })

    mock_ollama_resp = {"response": mock_response}

    with (
        patch("core.identity.assertions._regex_prefilter", return_value=True),
        patch("ollama.Client") as mock_client_cls,
    ):
        mock_client = MagicMock()
        mock_client.generate.return_value = mock_ollama_resp
        mock_client_cls.return_value = mock_client

        # Stub vault lookup to return empty (isolate classifier test)
        with patch("core.identity.assertions._vault_lookup", return_value=[]):
            result = check_assertion("I moved to Seattle")

    assert result.contains_assertion is True
    assert result.assertion_type == "location"
    assert result.extracted_claim == "I moved to Seattle"


# ---------------------------------------------------------------------------
# Test 5: Classifier returns non-assertion — clean result
# ---------------------------------------------------------------------------

def test_check_assertion_classifier_negative():
    """check_assertion returns clean AssertionResult when classifier says no assertion."""
    mock_response = json.dumps({
        "contains_assertion": False,
        "assertion_type": "none",
        "extracted_claim": None,
    })

    with (
        patch("core.identity.assertions._regex_prefilter", return_value=True),
        patch("ollama.Client") as mock_client_cls,
    ):
        mock_client = MagicMock()
        mock_client.generate.return_value = {"response": mock_response}
        mock_client_cls.return_value = mock_client

        result = check_assertion("I'm thinking about moving to Seattle")

    assert result.contains_assertion is False
    assert result.assertion_type == "none"
    assert result.extracted_claim is None
    assert result.vault_chunks == []


# ---------------------------------------------------------------------------
# Test 6: Classifier graceful degradation — exception returns clean result
# ---------------------------------------------------------------------------

def test_check_assertion_classifier_exception():
    """Exception in classifier yields clean AssertionResult (never raises)."""
    with (
        patch("core.identity.assertions._regex_prefilter", return_value=True),
        patch("ollama.Client") as mock_client_cls,
    ):
        mock_client = MagicMock()
        mock_client.generate.side_effect = ConnectionError("Ollama unreachable")
        mock_client_cls.return_value = mock_client

        result = check_assertion("I moved to Seattle")

    assert result.contains_assertion is False
    assert result.vault_chunks == []


# ---------------------------------------------------------------------------
# Test 7: Vault lookup triggered — non-empty chunks returned
# ---------------------------------------------------------------------------

def test_vault_lookup_triggered_and_returned():
    """When classifier finds assertion, vault_lookup is called and chunks returned."""
    mock_response = json.dumps({
        "contains_assertion": True,
        "assertion_type": "location",
        "extracted_claim": "I moved to Seattle",
    })

    mock_chunk = {"source_path": "vault/identity/GOALS.md", "content": "Location: Springfield, VA"}

    with (
        patch("core.identity.assertions._regex_prefilter", return_value=True),
        patch("ollama.Client") as mock_client_cls,
        patch("core.identity.assertions._vault_lookup", return_value=[mock_chunk]) as mock_lookup,
    ):
        mock_client = MagicMock()
        mock_client.generate.return_value = {"response": mock_response}
        mock_client_cls.return_value = mock_client

        result = check_assertion("I moved to Seattle")

    mock_lookup.assert_called_once_with("I moved to Seattle")
    assert len(result.vault_chunks) == 1
    assert result.vault_chunks[0]["source_path"] == "vault/identity/GOALS.md"


# ---------------------------------------------------------------------------
# Test 8: log_assertion writes JSONL with correct fields
# ---------------------------------------------------------------------------

def test_log_assertion_writes_jsonl(tmp_path):
    """log_assertion creates JSONL file with correct entry format."""
    assertion = AssertionResult(
        contains_assertion=True,
        assertion_type="location",
        extracted_claim="I moved to Seattle",
        vault_chunks=[],
    )

    with patch("core.identity.assertions.ASSERTION_LOG_DIR", tmp_path):
        entry_id = log_assertion("session-abc", assertion, "new", None)

    # File must exist
    import os
    from datetime import datetime, timezone
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    log_file = tmp_path / f"{date_str}.jsonl"
    assert log_file.exists()

    # Parse and verify
    with open(log_file, encoding="utf-8") as fh:
        entry = json.loads(fh.read().strip())

    assert entry["id"] == entry_id
    assert entry["session_id"] == "session-abc"
    assert entry["assertion_type"] == "location"
    assert entry["extracted_claim"] == "I moved to Seattle"
    assert entry["vault_result"] == "new"
    assert entry["nli_contradiction"] is False
    assert entry["delivered"] is False


# ---------------------------------------------------------------------------
# Test 9: load_undelivered_assertions filters delivered entries
# ---------------------------------------------------------------------------

def test_load_undelivered_assertions(tmp_path):
    """load_undelivered_assertions returns only undelivered entries."""
    from datetime import datetime, timezone
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    log_file = tmp_path / f"{date_str}.jsonl"

    delivered_entry = {
        "id": "aaa11111",
        "timestamp": "2026-02-21T10:00:00+00:00",
        "session_id": "s1",
        "assertion_type": "location",
        "extracted_claim": "I live in Portland",
        "vault_result": "new",
        "nli_contradiction": False,
        "delivered": True,
    }
    undelivered_entry = {
        "id": "bbb22222",
        "timestamp": "2026-02-21T11:00:00+00:00",
        "session_id": "s2",
        "assertion_type": "employment",
        "extracted_claim": "I quit my job",
        "vault_result": "conflict",
        "nli_contradiction": True,
        "delivered": False,
    }

    with open(log_file, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(delivered_entry) + "\n")
        fh.write(json.dumps(undelivered_entry) + "\n")

    with patch("core.identity.assertions.ASSERTION_LOG_DIR", tmp_path):
        results = load_undelivered_assertions()

    assert len(results) == 1
    assert results[0]["id"] == "bbb22222"


# ---------------------------------------------------------------------------
# Test 10: Handler step 8a integration — check_assertion and log_assertion called
# ---------------------------------------------------------------------------

def test_handler_step_8a_fires(tmp_path):
    """execute_query step 8a: check_assertion and log_assertion are called."""
    assertion_result = AssertionResult(
        contains_assertion=True,
        assertion_type="location",
        extracted_claim="I moved to Seattle",
        vault_chunks=[],  # no vault conflict → logged as "new"
    )

    with (
        patch("core.cognition.handler.get_or_create_session", return_value={"session_id": "s1", "started_at": "t0"}),
        patch("core.cognition.handler.log_interaction"),
        patch("core.cognition.handler.log_interaction_complete"),
        patch("core.cognition.handler.detect_pii", return_value=MagicMock(has_pii=False, entities=[])),
        patch("core.cognition.handler.compile_context", return_value=MagicMock(
            slices=[], total_tokens=0, budget=6000, query="q"
        )),
        patch("core.cognition.handler.render_context", return_value="ctx"),
        patch("core.cognition.handler.load_system_prompt", return_value="sys"),
        patch("core.cognition.handler.route_query", return_value=MagicMock(
            route=MagicMock(value="local"),
            cosine_gate_fired=False,
            reason="local",
            timestamp="t",
        )),
        patch("core.cognition.handler.generate_local", return_value={
            "response": "Standing by.", "logprobs": None
        }),
        patch("core.cognition.handler.score_response", return_value=MagicMock(
            score=80.0, method="test", hedging_flags=[]
        )),
        patch("core.cognition.handler.log_routing_decision"),
        patch("core.autonomic.fsm.get_current_state", side_effect=Exception("fsm skip")),
        patch("core.identity.input_guard.detect_adversarial", return_value=MagicMock(is_adversarial=False)),
        patch("core.identity.coherence.check_coherence", return_value=MagicMock(
            is_coherent=True, warning_message=None
        )),
        patch("core.safety.output_filter.check_output_sensitivity", return_value=MagicMock(
            level="CLEAN", response="Standing by.", triggered=[]
        )),
        patch("core.identity.assertions.check_assertion", return_value=assertion_result) as mock_check,
        patch("core.identity.assertions.log_assertion", return_value="deadbeef") as mock_log,
    ):
        from core.cognition.handler import execute_query
        result = execute_query("I moved to Seattle", force_local=True)

    mock_check.assert_called_once_with("I moved to Seattle")
    mock_log.assert_called_once_with("s1", assertion_result, "new", None)
