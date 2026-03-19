"""Tests for cloud bridge module."""

from unittest.mock import MagicMock, patch

import pytest


# ── Client initialization ───────────────────────────────────────────


def test_get_cloud_client_no_key():
    import core.cognition.cloud as cloud_mod
    cloud_mod._client = None  # reset cached client

    with patch.dict("os.environ", {}, clear=True):
        with pytest.raises(ValueError, match="GEMINI_API_KEY not set"):
            cloud_mod.get_cloud_client()


def test_get_cloud_client_success():
    import core.cognition.cloud as cloud_mod
    cloud_mod._client = None

    with patch.dict("os.environ", {"GEMINI_API_KEY": "test-key"}):
        with patch("core.cognition.cloud.genai.Client") as mock_cls:
            mock_cls.return_value = MagicMock()
            client = cloud_mod.get_cloud_client()
            assert client is not None
            mock_cls.assert_called_once()
    cloud_mod._client = None  # cleanup


# ── send_to_cloud ───────────────────────────────────────────────────


def _mock_response(text="Cloud answer", input_tok=100, output_tok=50):
    resp = MagicMock()
    resp.text = text
    resp.usage_metadata.prompt_token_count = input_tok
    resp.usage_metadata.candidates_token_count = output_tok
    return resp


def test_send_to_cloud_success():
    import core.cognition.cloud as cloud_mod
    cloud_mod._client = None

    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = _mock_response()

    with patch("core.cognition.cloud.get_cloud_client", return_value=mock_client):
        result = cloud_mod.send_to_cloud("test query", "context block")

    assert result.text == "Cloud answer"
    assert result.input_tokens == 100
    assert result.output_tokens == 50
    assert result.latency_ms >= 0


def test_send_to_cloud_server_error_retries():
    from google.genai.errors import APIError
    import core.cognition.cloud as cloud_mod
    cloud_mod._client = None

    mock_client = MagicMock()
    err = APIError("Internal Server Error", {})
    err.code = 500
    mock_client.models.generate_content.side_effect = err

    with patch("core.cognition.cloud.get_cloud_client", return_value=mock_client):
        with pytest.raises(APIError):
            cloud_mod.send_to_cloud("test", "ctx")

    assert mock_client.models.generate_content.call_count == 2


def test_send_to_cloud_client_error_no_retry():
    from google.genai.errors import APIError
    import core.cognition.cloud as cloud_mod
    cloud_mod._client = None

    mock_client = MagicMock()
    err = APIError("Bad Request", {})
    err.code = 400
    mock_client.models.generate_content.side_effect = err

    with patch("core.cognition.cloud.get_cloud_client", return_value=mock_client):
        with pytest.raises(APIError):
            cloud_mod.send_to_cloud("test", "ctx")

    assert mock_client.models.generate_content.call_count == 1  # no retry


# ── stream_cloud ────────────────────────────────────────────────────


def test_stream_cloud_yields_deltas():
    import core.cognition.cloud as cloud_mod
    cloud_mod._client = None

    mock_client = MagicMock()
    mock_client.models.generate_content_stream.return_value = [
        MagicMock(text="Hello"),
        MagicMock(text=" World")
    ]

    with patch("core.cognition.cloud.get_cloud_client", return_value=mock_client):
        deltas = list(cloud_mod.stream_cloud("test", "ctx"))

    assert deltas == ["Hello", " World"]


def test_stream_cloud_empty_response():
    import core.cognition.cloud as cloud_mod
    cloud_mod._client = None

    mock_client = MagicMock()
    mock_client.models.generate_content_stream.return_value = []

    with patch("core.cognition.cloud.get_cloud_client", return_value=mock_client):
        deltas = list(cloud_mod.stream_cloud("test", "ctx"))

    assert deltas == []
