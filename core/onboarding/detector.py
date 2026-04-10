"""Backend auto-detection — scan known localhost ports for inference servers."""
from __future__ import annotations

import asyncio
import logging

import httpx

log = logging.getLogger(__name__)

BACKENDS = [
    {"name": "ollama", "port": 11434, "health": "/api/tags", "models": "/api/tags", "model_key": "models"},
    {"name": "lm-studio", "port": 1234, "health": "/v1/models", "models": "/v1/models", "model_key": "data"},
    {"name": "llama-cpp", "port": 8080, "health": "/health", "models": "/v1/models", "model_key": "data"},
    {"name": "vllm", "port": 8000, "health": "/v1/models", "models": "/v1/models", "model_key": "data"},
    {"name": "sglang", "port": 30000, "health": "/health", "models": "/v1/models", "model_key": "data"},
    {"name": "tabbyapi", "port": 5000, "health": "/v1/models", "models": "/v1/models", "model_key": "data"},
]

BACKEND_DISPLAY_NAMES = {
    "ollama": "Ollama",
    "lm-studio": "LM Studio",
    "llama-cpp": "llama.cpp Server",
    "vllm": "vLLM",
    "sglang": "SGLang",
    "tabbyapi": "ExLlamaV2 (TabbyAPI)",
}


class BackendDetector:
    def __init__(self, timeout: float = 0.5):
        self._timeout = timeout

    async def scan(self) -> list[dict]:
        """Scan all known ports concurrently. Returns detected backends with models."""
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            tasks = [self._probe(client, b) for b in BACKENDS]
            results = await asyncio.gather(*tasks, return_exceptions=True)
        return [r for r in results if isinstance(r, dict)]

    async def _probe(self, client: httpx.AsyncClient, backend: dict) -> dict | None:
        url = f"http://localhost:{backend['port']}{backend['health']}"
        try:
            resp = await client.get(url)
            if resp.status_code != 200:
                return None
            data = resp.json()
            models = []
            raw_models = data.get(backend["model_key"], [])
            if isinstance(raw_models, list):
                for m in raw_models:
                    if isinstance(m, dict):
                        name = m.get("name") or m.get("id", "unknown")
                        size = m.get("size", 0)
                        models.append({"name": name, "size_bytes": size})
            return {
                "backend": backend["name"],
                "display_name": BACKEND_DISPLAY_NAMES.get(backend["name"], backend["name"]),
                "port": backend["port"],
                "url": f"http://localhost:{backend['port']}",
                "models": models,
            }
        except Exception:
            return None


def detect_backends() -> list[dict]:
    """Synchronous wrapper for BackendDetector.scan()."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop and loop.is_running():
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as pool:
            return pool.submit(lambda: asyncio.run(BackendDetector().scan())).result(timeout=10)
    return asyncio.run(BackendDetector().scan())
