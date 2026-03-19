"""Tests for the Ollama local inference wrapper."""

from unittest.mock import MagicMock, patch

import ollama as _ollama

from core.cognition.inference import (
    check_inference_model,
    check_logprob_support,
    generate_local,
    load_system_prompt,
)


@patch("core.cognition.inference.get_inference_client")
def test_generate_local_success(mock_client):
    client = MagicMock()
    client.generate.return_value = {
        "response": "Hello world",
        "eval_count": 5,
        "eval_duration": 1000,
    }
    mock_client.return_value = client

    result = generate_local("Say hello")
    assert result["response"] == "Hello world"
    assert result["eval_count"] == 5
    assert result["logprobs"] is None


@patch("core.cognition.inference.get_inference_client")
def test_generate_local_with_logprobs(mock_client):
    client = MagicMock()
    client.generate.return_value = {
        "response": "Test",
        "logprobs": [{"token": "Test", "logprob": -0.1}],
        "eval_count": 1,
        "eval_duration": 100,
    }
    mock_client.return_value = client

    result = generate_local("Test prompt")
    assert result["logprobs"] is not None
    assert len(result["logprobs"]) == 1


@patch("core.cognition.inference.get_inference_client")
def test_generate_local_with_system_prompt(mock_client):
    client = MagicMock()
    client.generate.return_value = {"response": "OK", "eval_count": 1, "eval_duration": 50}
    mock_client.return_value = client

    generate_local("query", system="You are helpful.")
    kwargs = client.generate.call_args
    assert kwargs[1]["system"] == "You are helpful."


@patch("core.cognition.inference.get_inference_client")
def test_generate_local_connection_error(mock_client):
    client = MagicMock()
    client.generate.side_effect = ConnectionError("Ollama down")
    mock_client.return_value = client

    result = generate_local("test")
    assert "error" in result
    assert result["response"] == ""


@patch("core.cognition.inference.get_inference_client")
def test_generate_local_model_not_found(mock_client):
    client = MagicMock()
    client.generate.side_effect = _ollama.ResponseError("model not found")
    mock_client.return_value = client

    result = generate_local("test")
    assert "error" in result
    assert result["response"] == ""


@patch("core.cognition.inference.get_inference_client")
def test_check_inference_model_available(mock_client):
    client = MagicMock()
    model = MagicMock()
    model.model = "qwen2.5:14b"
    client.list.return_value = MagicMock(models=[model])
    mock_client.return_value = client

    assert check_inference_model() is True


@patch("core.cognition.inference.get_inference_client")
def test_check_inference_model_missing(mock_client):
    client = MagicMock()
    client.list.return_value = MagicMock(models=[])
    mock_client.return_value = client

    assert check_inference_model() is False


@patch("core.cognition.inference._LOGPROBS_AVAILABLE", None)
@patch("core.cognition.inference.get_inference_client")
def test_check_logprob_support_available(mock_client):
    client = MagicMock()
    client.generate.return_value = {"response": "hi", "logprobs": [{"token": "hi", "logprob": -0.05}]}
    mock_client.return_value = client

    assert check_logprob_support() is True


@patch("core.cognition.inference._LOGPROBS_AVAILABLE", None)
@patch("core.cognition.inference.get_inference_client")
def test_check_logprob_support_unavailable(mock_client):
    client = MagicMock()
    client.generate.return_value = {"response": "hi"}
    mock_client.return_value = client

    assert check_logprob_support() is False


def test_load_system_prompt(tmp_path):
    pattern_dir = tmp_path / "vault" / "patterns" / "test_pattern"
    pattern_dir.mkdir(parents=True)
    (pattern_dir / "system.md").write_text("You are a test assistant.", encoding="utf-8")

    with patch("core.cognition.inference.VAULT_DIR", tmp_path / "vault"):
        result = load_system_prompt("test_pattern")
    assert result == "You are a test assistant."


def test_load_system_prompt_missing(tmp_path):
    with patch("core.cognition.inference.VAULT_DIR", tmp_path / "vault"):
        result = load_system_prompt("nonexistent")
    assert result == ""
