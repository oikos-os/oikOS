"""Tests for NLI contradiction check module."""

import json
from unittest.mock import MagicMock, patch

from core.identity.contradiction import check_contradiction
from core.interface.models import CloudResponse, ContradictionResult


def _mock_cloud_response(data: dict) -> CloudResponse:
    return CloudResponse(
        text=json.dumps(data),
        model="claude-sonnet",
        input_tokens=100,
        output_tokens=50,
        latency_ms=200,
    )


def test_identity_contradiction_detected():
    cloud_data = {
        "has_contradiction": True,
        "contradiction_type": "identity",
        "confidence": 85,
        "explanation": "Response says Architect is 25 but vault says 31.",
    }
    with patch("core.cognition.cloud.send_to_cloud", return_value=_mock_cloud_response(cloud_data)):
        result = check_contradiction("The Architect is 25.", [{"source_path": "vault/identity/BIO.md", "content": "Age: 31"}])

    assert result.has_contradiction is True
    assert result.contradiction_type == "identity"
    assert result.confidence == 85


def test_knowledge_contradiction_detected():
    cloud_data = {
        "has_contradiction": True,
        "contradiction_type": "knowledge",
        "confidence": 70,
        "explanation": "Incorrect model reference.",
    }
    with patch("core.cognition.cloud.send_to_cloud", return_value=_mock_cloud_response(cloud_data)):
        result = check_contradiction("We use GPT-4.", [{"source_path": "vault/knowledge/STACK.md", "content": "Model: llama3"}])

    assert result.has_contradiction is True
    assert result.contradiction_type == "knowledge"


def test_no_contradiction_passthrough():
    cloud_data = {
        "has_contradiction": False,
        "contradiction_type": "none",
        "confidence": 95,
        "explanation": "No contradictions found.",
    }
    with patch("core.cognition.cloud.send_to_cloud", return_value=_mock_cloud_response(cloud_data)):
        result = check_contradiction("Python 3.12 is used.", [{"source_path": "vault/knowledge/STACK.md", "content": "Python 3.12+"}])

    assert result.has_contradiction is False


def test_low_confidence_contradiction():
    cloud_data = {
        "has_contradiction": True,
        "contradiction_type": "identity",
        "confidence": 40,
        "explanation": "Might be a contradiction.",
    }
    with patch("core.cognition.cloud.send_to_cloud", return_value=_mock_cloud_response(cloud_data)):
        result = check_contradiction("Something ambiguous.", [{"source_path": "test.md", "content": "test"}])

    # Result returned as-is; caller decides threshold
    assert result.has_contradiction is True
    assert result.confidence == 40


def test_empty_vault_chunks():
    result = check_contradiction("Some response.", [])
    assert result.has_contradiction is False
    assert "No vault chunks" in result.explanation


def test_cloud_failure_graceful_degradation():
    with patch("core.cognition.cloud.send_to_cloud", side_effect=Exception("API down")):
        result = check_contradiction("Test.", [{"source_path": "test.md", "content": "test"}])

    assert result.has_contradiction is False
    assert "Cloud unavailable" in result.explanation


def test_nli_prompt_contains_chunks():
    captured_args = {}

    def _capture_send(query, context, model=None):
        captured_args["query"] = query
        return _mock_cloud_response({
            "has_contradiction": False,
            "contradiction_type": "none",
            "confidence": 0,
            "explanation": "",
        })

    chunks = [
        {"source_path": "vault/identity/BIO.md", "content": "Age: 31, Role: Team Lead"},
        {"source_path": "vault/identity/GOALS.md", "content": "Ship OIKOS OMEGA"},
    ]
    with patch("core.cognition.cloud.send_to_cloud", side_effect=_capture_send):
        check_contradiction("The Architect is a musician.", chunks)

    assert "vault/identity/BIO.md" in captured_args["query"]
    assert "Age: 31" in captured_args["query"]
    assert "The Architect is a musician." in captured_args["query"]


def test_json_in_code_block():
    """Cloud sometimes wraps JSON in markdown code blocks."""
    resp = CloudResponse(
        text='```json\n{"has_contradiction": true, "contradiction_type": "identity", "confidence": 80, "explanation": "test"}\n```',
        model="claude-sonnet",
        input_tokens=100,
        output_tokens=50,
        latency_ms=200,
    )
    with patch("core.cognition.cloud.send_to_cloud", return_value=resp):
        result = check_contradiction("test", [{"source_path": "test.md", "content": "test"}])

    assert result.has_contradiction is True
    assert result.contradiction_type == "identity"
