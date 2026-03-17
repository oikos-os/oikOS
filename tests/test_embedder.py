"""Tests for the Ollama embedding wrapper."""

from unittest.mock import MagicMock, patch

from core.interface.config import EMBED_DIMS
from core.memory.embedder import check_health, embed_batch, embed_single


def _fake_embed_response(texts):
    """Return fake embeddings of correct dimensionality."""
    if isinstance(texts, str):
        texts = [texts]
    return {"embeddings": [[0.1] * EMBED_DIMS for _ in texts]}


@patch("core.memory.embedder.get_client")
def test_embed_single_dimensions(mock_client):
    client = MagicMock()
    client.embed.return_value = _fake_embed_response("test")
    mock_client.return_value = client

    vec = embed_single("test query")
    assert len(vec) == EMBED_DIMS
    assert all(isinstance(v, float) for v in vec)


@patch("core.memory.embedder.get_client")
def test_embed_batch_dimensions(mock_client):
    client = MagicMock()
    client.embed.side_effect = lambda model, input: _fake_embed_response(input)
    mock_client.return_value = client

    texts = ["hello", "world", "test"]
    vecs = embed_batch(texts)
    assert len(vecs) == 3
    assert all(len(v) == EMBED_DIMS for v in vecs)


@patch("core.memory.embedder.get_client")
def test_embed_batch_sub_batching(mock_client):
    """Batch of 20 should result in 2 API calls (batch size 16)."""
    client = MagicMock()
    client.embed.side_effect = lambda model, input: _fake_embed_response(input)
    mock_client.return_value = client

    texts = [f"text_{i}" for i in range(20)]
    vecs = embed_batch(texts)
    assert len(vecs) == 20
    assert client.embed.call_count == 2  # 16 + 4


@patch("core.memory.embedder.get_client")
def test_check_health_ok(mock_client):
    client = MagicMock()
    model = MagicMock()
    model.model = "nomic-embed-text:v1.5"
    client.list.return_value = MagicMock(models=[model])
    mock_client.return_value = client

    assert check_health() is True


@patch("core.memory.embedder.get_client")
def test_check_health_no_model(mock_client):
    client = MagicMock()
    client.list.return_value = MagicMock(models=[])
    mock_client.return_value = client

    assert check_health() is False


@patch("core.memory.embedder.get_client")
def test_check_health_connection_error(mock_client):
    mock_client.side_effect = Exception("Connection refused")

    assert check_health() is False
