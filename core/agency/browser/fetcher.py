"""Layer 1 web fetcher — httpx + readability-lxml. No Playwright."""

from __future__ import annotations

import re

import httpx
from readability import Document


class WebFetcher:
    """Fetches web pages and extracts readable content as text."""

    def __init__(self, timeout: float = 15.0):
        self._client = httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=True,
            headers={"User-Agent": "oikOS/1.1 (web-fetch)"},
        )

    async def fetch(self, url: str, max_tokens: int = 6000) -> dict:
        try:
            response = await self._client.get(url)
        except httpx.TimeoutException:
            return {"status": "error", "message": "Request timed out (15s)"}
        except Exception:
            return {"status": "error", "message": "Connection failed"}

        if response.status_code != 200:
            return {"status": "error", "message": f"HTTP {response.status_code}"}

        doc = Document(response.text)
        title = doc.short_title() or ""
        content = doc.summary(html_partial=True)

        # Strip HTML tags for plain text
        text = re.sub(r"<[^>]+>", "", content)
        text = re.sub(r"\s+", " ", text).strip()

        # Token estimation and truncation
        words = text.split()
        estimated_tokens = int(len(words) * 1.3)
        truncated = False
        if estimated_tokens > max_tokens:
            keep_words = int(max_tokens / 1.3)
            words = words[:keep_words]
            text = " ".join(words)
            estimated_tokens = max_tokens
            truncated = True

        return {
            "url": str(response.url),
            "title": title,
            "content": text,
            "content_tokens": estimated_tokens,
            "truncated": truncated,
        }

    async def close(self):
        await self._client.aclose()
