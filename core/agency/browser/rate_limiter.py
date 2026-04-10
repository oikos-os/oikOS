"""Per-domain token-bucket rate limiter for browser tools."""

from __future__ import annotations

import asyncio
import time
from urllib.parse import urlparse


class DomainRateLimiter:
    """Token-bucket rate limiter keyed by domain.

    All browser tools share one instance via BrowserManager.
    """

    class RateLimitedError(Exception):
        def __init__(self, domain: str, retry_after: float):
            self.domain = domain
            self.retry_after = retry_after
            super().__init__(f"Rate limited: {domain} (retry after {retry_after:.1f}s)")

    def __init__(self, rate: float = 2.0, burst: int | None = None):
        self._rate = rate  # tokens per second
        self._burst = burst if burst is not None else max(int(rate), 1)
        self._buckets: dict[str, tuple[float, float]] = {}  # domain -> (tokens, last_refill)
        self._locks: dict[str, asyncio.Lock] = {}

    def _extract_domain(self, url: str) -> str:
        parsed = urlparse(url)
        if not parsed.hostname:
            raise ValueError(f"Cannot extract domain from URL: {url}")
        return parsed.hostname

    def _get_lock(self, domain: str) -> asyncio.Lock:
        return self._locks.setdefault(domain, asyncio.Lock())

    async def acquire(self, url: str) -> None:
        domain = self._extract_domain(url)
        lock = self._get_lock(domain)
        async with lock:
            now = time.monotonic()
            if domain not in self._buckets:
                self._buckets[domain] = (float(self._burst), now)

            tokens, last_refill = self._buckets[domain]
            elapsed = now - last_refill
            tokens = min(self._burst, tokens + elapsed * self._rate)

            if tokens < 1.0:
                wait = (1.0 - tokens) / self._rate
                self._buckets[domain] = (tokens, now)
                raise self.RateLimitedError(domain, wait)

            self._buckets[domain] = (tokens - 1.0, now)
