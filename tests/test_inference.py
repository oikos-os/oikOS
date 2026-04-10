"""Tests for the Ollama local inference wrapper."""

from unittest.mock import MagicMock, patch

import ollama as _ollama

from core.cognition.inference import (
    check_inference_model,
    check_logprob_support,
    generate_local,
    generate_routed,
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


# ── generate_routed tests ──────────────────────────────────────────────


@patch("core.cognition.inference.generate_local")
@patch("core.cognition.pipeline.dispatch.get_provider_router")
def test_generate_routed_success(mock_get_router, mock_local):
    """Router succeeds — returns provider response, local not called."""
    mock_router = MagicMock()
    mock_result = MagicMock()
    mock_result.text = "cloud response"
    mock_router.route.return_value = mock_result
    mock_get_router.return_value = mock_router

    result = generate_routed("hello", system="sys")
    assert result["response"] == "cloud response"
    assert result["logprobs"] is None
    mock_local.assert_not_called()


@patch("core.cognition.inference.generate_local")
@patch("core.cognition.pipeline.dispatch.get_provider_router")
def test_generate_routed_router_fails_falls_to_local(mock_get_router, mock_local):
    """Router raises — falls back to generate_local."""
    mock_get_router.return_value.route.side_effect = RuntimeError("no provider")
    mock_local.return_value = {"response": "local fallback", "logprobs": None}

    result = generate_routed("hello")
    assert result["response"] == "local fallback"
    mock_local.assert_called_once()


@patch("core.cognition.inference.generate_local")
@patch("core.cognition.pipeline.dispatch.get_provider_router")
def test_generate_routed_fallback_preserves_kwargs(mock_get_router, mock_local):
    """Router failure preserves num_predict and temperature for generate_local fallback."""
    mock_get_router.return_value.route.side_effect = RuntimeError("fail")
    mock_local.return_value = {"response": "ok", "logprobs": None}

    generate_routed("q", model="qwen2.5:7b", num_predict=512, temperature=0.3)
    _, call_kwargs = mock_local.call_args
    assert call_kwargs["num_predict"] == 512
    assert call_kwargs["temperature"] == 0.3
    assert call_kwargs["model"] == "qwen2.5:7b"


@patch("core.cognition.inference.generate_local")
@patch("core.cognition.pipeline.dispatch.get_provider_router", side_effect=ImportError)
def test_generate_routed_router_unavailable(mock_get_router, mock_local):
    """Router import fails — falls back to generate_local."""
    mock_local.return_value = {"response": "local", "logprobs": None}

    result = generate_routed("test")
    assert result["response"] == "local"


@patch("core.cognition.inference.generate_local")
@patch("core.cognition.pipeline.dispatch.get_provider_router")
def test_generate_routed_passes_model_kwarg(mock_get_router, mock_local):
    """Model arg is forwarded to router.route()."""
    mock_router = MagicMock()
    mock_result = MagicMock()
    mock_result.text = "ok"
    mock_router.route.return_value = mock_result
    mock_get_router.return_value = mock_router

    generate_routed("q", model="gemini-2.5-pro")
    call_kwargs = mock_router.route.call_args
    assert call_kwargs[1]["model"] == "gemini-2.5-pro"


@patch("core.cognition.inference.generate_local")
@patch("core.cognition.pipeline.dispatch.get_provider_router")
def test_generate_routed_maps_num_predict_to_max_tokens(mock_get_router, mock_local):
    """num_predict option maps to max_tokens for the provider."""
    mock_router = MagicMock()
    mock_result = MagicMock()
    mock_result.text = "ok"
    mock_router.route.return_value = mock_result
    mock_get_router.return_value = mock_router

    generate_routed("q", num_predict=512)
    call_kwargs = mock_router.route.call_args
    assert call_kwargs[1]["max_tokens"] == 512
