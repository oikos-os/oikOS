"""Tests for EmbedderProvider protocol and OllamaEmbedder implementation."""

from __future__ import annotations

from unittest.mock import MagicMock, patch


# ── Helpers ───────────────────────────────────────────────────────────────

DIMS = 768


def _fake_embed_response(texts):
    """Return fake embeddings of correct dimensionality."""
    if isinstance(texts, str):
        texts = [texts]
    return {"embeddings": [[0.1] * DIMS for _ in texts]}


# ── Protocol Conformance ─────────────────────────────────────────────────


class TestProtocolConformance:
    """OllamaEmbedder must satisfy the EmbedderProvider protocol."""

    def test_isinstance_check(self):
        from core.memory.embedder_protocol import EmbedderProvider
        from core.memory.ollama_embedder import OllamaEmbedder

        embedder = OllamaEmbedder()
        assert isinstance(embedder, EmbedderProvider)

    def test_has_provider_name(self):
        from core.memory.ollama_embedder import OllamaEmbedder

        embedder = OllamaEmbedder()
        assert hasattr(embedder, "provider_name")
        assert embedder.provider_name == "ollama"

    def test_has_dims(self):
        from core.memory.ollama_embedder import OllamaEmbedder

        embedder = OllamaEmbedder()
        assert hasattr(embedder, "dims")
        assert embedder.dims == DIMS


# ── embed_single ─────────────────────────────────────────────────────────


class TestOllamaEmbedderEmbedSingle:
    """Tests for OllamaEmbedder.embed_single()."""

    @patch("core.memory.ollama_embedder.OllamaEmbedder._get_client")
    def test_correct_dims_returned(self, mock_get_client):
        from core.memory.ollama_embedder import OllamaEmbedder

        client = MagicMock()
        client.embed.return_value = _fake_embed_response("test")
        mock_get_client.return_value = client

        embedder = OllamaEmbedder()
        vec = embedder.embed_single("test query")

        assert len(vec) == DIMS
        assert all(isinstance(v, float) for v in vec)

    @patch("core.memory.ollama_embedder.OllamaEmbedder._get_client")
    def test_empty_text_returns_zero_vector(self, mock_get_client):
        from core.memory.ollama_embedder import OllamaEmbedder

        embedder = OllamaEmbedder()
        vec = embedder.embed_single("")

        assert len(vec) == DIMS
        assert all(v == 0.0 for v in vec)
        # Should not call the client at all
        mock_get_client.assert_not_called()

    @patch("core.memory.ollama_embedder.OllamaEmbedder._get_client")
    def test_whitespace_only_returns_zero_vector(self, mock_get_client):
        from core.memory.ollama_embedder import OllamaEmbedder

        embedder = OllamaEmbedder()
        vec = embedder.embed_single("   \t\n  ")

        assert len(vec) == DIMS
        assert all(v == 0.0 for v in vec)
        mock_get_client.assert_not_called()

    @patch("core.memory.ollama_embedder.OllamaEmbedder._get_client")
    def test_calls_client_with_correct_model(self, mock_get_client):
        from core.memory.ollama_embedder import OllamaEmbedder

        client = MagicMock()
        client.embed.return_value = _fake_embed_response("hello")
        mock_get_client.return_value = client

        embedder = OllamaEmbedder(model="custom-model:v2")
        embedder.embed_single("hello world")

        client.embed.assert_called_once_with(
            model="custom-model:v2", input="hello world"
        )


# ── embed_batch ──────────────────────────────────────────────────────────


class TestOllamaEmbedderBatch:
    """Tests for OllamaEmbedder.embed_batch()."""

    @patch("core.memory.ollama_embedder.OllamaEmbedder._get_client")
    def test_correct_count_returned(self, mock_get_client):
        from core.memory.ollama_embedder import OllamaEmbedder

        client = MagicMock()
        client.embed.side_effect = lambda model, input: _fake_embed_response(input)
        mock_get_client.return_value = client

        embedder = OllamaEmbedder()
        texts = ["hello", "world", "test"]
        vecs = embedder.embed_batch(texts)

        assert len(vecs) == 3
        assert all(len(v) == DIMS for v in vecs)

    @patch("core.memory.ollama_embedder.OllamaEmbedder._get_client")
    def test_sub_batching_at_boundary(self, mock_get_client):
        """20 texts with batch_size=16 should produce 2 API calls (16 + 4)."""
        from core.memory.ollama_embedder import OllamaEmbedder

        client = MagicMock()
        client.embed.side_effect = lambda model, input: _fake_embed_response(input)
        mock_get_client.return_value = client

        embedder = OllamaEmbedder(batch_size=16)
        texts = [f"text_{i}" for i in range(20)]
        vecs = embedder.embed_batch(texts)

        assert len(vecs) == 20
        assert client.embed.call_count == 2  # 16 + 4

    @patch("core.memory.ollama_embedder.OllamaEmbedder._get_client")
    def test_empty_list_returns_empty(self, mock_get_client):
        """embed_batch([]) should return [] without hitting client."""
        from core.memory.ollama_embedder import OllamaEmbedder

        embedder = OllamaEmbedder()
        result = embedder.embed_batch([])

        assert result == []
        mock_get_client.assert_not_called()

    @patch("core.memory.ollama_embedder.OllamaEmbedder._get_client")
    def test_empty_texts_get_zero_vectors(self, mock_get_client):
        """Empty/whitespace texts in a batch get zero vectors at correct indices."""
        from core.memory.ollama_embedder import OllamaEmbedder

        client = MagicMock()
        # Only non-empty texts hit the API -- "hello" is the only valid one
        client.embed.return_value = _fake_embed_response("hello")
        mock_get_client.return_value = client

        embedder = OllamaEmbedder()
        result = embedder.embed_batch(["", "hello", "  "])

        assert len(result) == 3
        assert all(v == 0.0 for v in result[0])  # empty -> zero vec
        assert result[1] == [0.1] * DIMS  # real embedding
        assert all(v == 0.0 for v in result[2])  # whitespace -> zero vec


# ── base_url Constructor Path ────────────────────────────────────────────


class TestOllamaEmbedderBaseUrl:
    """Tests for base_url constructor parameter."""

    def test_get_client_passes_host_when_base_url_set(self):
        """_get_client should pass host= when base_url is configured."""
        from core.memory.ollama_embedder import OllamaEmbedder

        embedder = OllamaEmbedder(base_url="http://remote:11434")
        with patch("ollama.Client", return_value=MagicMock()) as mock_client_cls:
            embedder._get_client()
            mock_client_cls.assert_called_once_with(host="http://remote:11434")

    def test_get_client_no_host_when_base_url_none(self):
        """_get_client should call Client() with no host when base_url is None."""
        from core.memory.ollama_embedder import OllamaEmbedder

        embedder = OllamaEmbedder(base_url=None)
        with patch("ollama.Client", return_value=MagicMock()) as mock_client_cls:
            embedder._get_client()
            mock_client_cls.assert_called_once_with()


# ── Availability ─────────────────────────────────────────────────────────


class TestOllamaEmbedderAvailability:
    """Tests for OllamaEmbedder.is_available()."""

    @patch("core.memory.ollama_embedder.OllamaEmbedder._get_client")
    def test_model_present_returns_true(self, mock_get_client):
        from core.memory.ollama_embedder import OllamaEmbedder

        client = MagicMock()
        model = MagicMock()
        model.model = "nomic-embed-text:v1.5"
        client.list.return_value = MagicMock(models=[model])
        mock_get_client.return_value = client

        embedder = OllamaEmbedder()
        assert embedder.is_available() is True

    @patch("core.memory.ollama_embedder.OllamaEmbedder._get_client")
    def test_connection_error_returns_false(self, mock_get_client):
        from core.memory.ollama_embedder import OllamaEmbedder

        mock_get_client.side_effect = Exception("Connection refused")

        embedder = OllamaEmbedder()
        assert embedder.is_available() is False

    @patch("core.memory.ollama_embedder.OllamaEmbedder._get_client")
    def test_model_not_in_list_returns_false(self, mock_get_client):
        from core.memory.ollama_embedder import OllamaEmbedder

        client = MagicMock()
        model = MagicMock()
        model.model = "llama3:latest"
        client.list.return_value = MagicMock(models=[model])
        mock_get_client.return_value = client

        embedder = OllamaEmbedder()
        assert embedder.is_available() is False
