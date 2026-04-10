"""OllamaEmbedder -- EmbedderProvider implementation backed by Ollama."""

from __future__ import annotations

import logging
import os

log = logging.getLogger(__name__)


class OllamaEmbedder:
    """Wraps Ollama embedding API behind the EmbedderProvider protocol."""

    provider_name: str = "ollama"

    def __init__(
        self,
        model: str = "nomic-embed-text:v1.5",
        dims: int = 768,
        batch_size: int = 16,
        base_url: str | None = None,
    ) -> None:
        self.model = model
        self.dims = dims
        self.batch_size = batch_size
        self.base_url = base_url

    # ── Core API ──────────────────────────────────────────────────────

    def embed_single(self, text: str) -> list[float]:
        """Embed a single text, returns dims-length float list."""
        if not text or not text.strip():
            log.warning("embed_single called with empty text, returning zero vector")
            return [0.0] * self.dims

        client = self._get_client()
        resp = client.embed(model=self.model, input=text)

        if not resp.get("embeddings") or len(resp["embeddings"]) == 0:
            log.error("Ollama returned empty embeddings array, returning zero vector")
            return [0.0] * self.dims

        vec = resp["embeddings"][0]
        if len(vec) != self.dims:
            log.warning("Expected %d dims, got %d", self.dims, len(vec))
        return vec

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed a list of texts in sub-batches of batch_size."""
        if not texts:
            return []

        # Track which indices are empty/whitespace and need zero vectors
        zero_vec = [0.0] * self.dims
        valid_indices: list[int] = []
        valid_texts: list[str] = []
        for i, t in enumerate(texts):
            if t and t.strip():
                valid_indices.append(i)
                valid_texts.append(t)

        # All texts were empty/whitespace
        if not valid_texts:
            return [list(zero_vec) for _ in texts]

        # Embed valid texts in sub-batches
        client = self._get_client()
        embedded: list[list[float]] = []
        for i in range(0, len(valid_texts), self.batch_size):
            batch = valid_texts[i : i + self.batch_size]
            resp = client.embed(model=self.model, input=batch)
            embeddings = resp.get("embeddings") or []
            if len(embeddings) != len(batch):
                log.error(
                    "Ollama returned %d embeddings for %d texts, padding with zeros",
                    len(embeddings),
                    len(batch),
                )
                embeddings.extend([list(zero_vec)] * (len(batch) - len(embeddings)))
            embedded.extend(embeddings)

        # Reassemble: place embeddings at valid indices, zeros elsewhere
        result: list[list[float]] = [list(zero_vec) for _ in texts]
        for idx, vec in zip(valid_indices, embedded):
            result[idx] = vec
        return result

    def is_available(self) -> bool:
        """Return True if Ollama is reachable and embed model is available."""
        try:
            client = self._get_client()
            models = client.list()
            available = [m.model for m in models.models]
            model_base = self.model.split(":")[0]
            return any(m.split(":")[0] == model_base for m in available)
        except Exception as e:
            log.debug("Ollama embedder health check failed: %s", e)
            return False

    # ── Internal ──────────────────────────────────────────────────────

    def _get_client(self):
        """Return an Ollama client. This is the mock target for tests."""
        import ollama as _ollama  # lazy import -- keeps module importable without ollama

        # Force CPU-only for embeddings -- leave GPU free for inference
        os.environ.setdefault("OLLAMA_NUM_GPU", "0")

        if self.base_url:
            return _ollama.Client(host=self.base_url)
        return _ollama.Client()
