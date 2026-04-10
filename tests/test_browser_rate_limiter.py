"""Tests for per-domain token-bucket rate limiter."""

import asyncio
import time
import pytest
from core.agency.browser.rate_limiter import DomainRateLimiter


class TestDomainRateLimiter:
    def test_extract_domain(self):
        rl = DomainRateLimiter(rate=2.0)
        assert rl._extract_domain("https://example.com/page") == "example.com"
        assert rl._extract_domain("http://sub.example.com:8080/path") == "sub.example.com"

    def test_allows_within_rate(self):
        rl = DomainRateLimiter(rate=10.0)
        loop = asyncio.new_event_loop()
        # 5 requests at rate=10/sec should all pass
        for _ in range(5):
            loop.run_until_complete(rl.acquire("https://example.com/page"))
        loop.close()

    def test_blocks_when_exhausted(self):
        rl = DomainRateLimiter(rate=2.0, burst=2)
        loop = asyncio.new_event_loop()
        # Exhaust the bucket
        loop.run_until_complete(rl.acquire("https://example.com/a"))
        loop.run_until_complete(rl.acquire("https://example.com/b"))
        # Third should raise
        with pytest.raises(rl.RateLimitedError) as exc:
            loop.run_until_complete(rl.acquire("https://example.com/c"))
        assert exc.value.retry_after > 0
        loop.close()

    def test_different_domains_independent(self):
        rl = DomainRateLimiter(rate=1.0, burst=1)
        loop = asyncio.new_event_loop()
        loop.run_until_complete(rl.acquire("https://a.com/page"))
        loop.run_until_complete(rl.acquire("https://b.com/page"))  # different domain, should pass
        loop.close()

    def test_tokens_refill_over_time(self):
        rl = DomainRateLimiter(rate=10.0, burst=1)
        loop = asyncio.new_event_loop()
        loop.run_until_complete(rl.acquire("https://example.com/a"))
        # Wait for refill
        time.sleep(0.15)
        loop.run_until_complete(rl.acquire("https://example.com/b"))  # should pass after refill
        loop.close()

    def test_invalid_url_raises(self):
        rl = DomainRateLimiter(rate=2.0)
        loop = asyncio.new_event_loop()
        with pytest.raises(ValueError, match="domain"):
            loop.run_until_complete(rl.acquire("not-a-url"))
        loop.close()
