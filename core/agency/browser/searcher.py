"""SearXNG search client — sovereign, self-hosted search."""

from __future__ import annotations

import httpx

SEARXNG_URL = "http://127.0.0.1:8888"


class SearXNGSearcher:
    """Client for SearXNG JSON API."""

    def __init__(self, base_url: str = SEARXNG_URL, timeout: float = 10.0):
        self._base_url = base_url
        self._client = httpx.AsyncClient(timeout=timeout)

    async def search(self, query: str, count: int = 10, engines: str = "") -> dict:
        params = {"q": query, "format": "json"}
        if engines:
            params["engines"] = engines

        try:
            response = await self._client.get(f"{self._base_url}/search", params=params)
        except Exception:
            return {"status": "error", "message": "Search engine unavailable"}

        if response.status_code != 200:
            return {"status": "error", "message": f"Search engine returned HTTP {response.status_code}"}

        data = response.json()
        results = [
            {"title": r.get("title", ""), "url": r.get("url", ""), "snippet": r.get("content", "")}
            for r in data.get("results", [])
        ][:count]

        return {"query": query, "results": results, "count": len(results)}

    async def close(self):
        await self._client.aclose()
