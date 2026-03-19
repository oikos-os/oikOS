"""Browser agency — web perception for oikOS.

BrowserManager is the central coordinator. All tools go through it.
"""

from __future__ import annotations

from core.agency.browser.rate_limiter import DomainRateLimiter
from core.agency.browser.fetcher import WebFetcher
from core.agency.browser.searcher import SearXNGSearcher
from core.agency.browser.playwright_pool import PlaywrightPool
from core.agency.browser.extractor import WebExtractor
from core.agency.browser.navigator import WebNavigator
from core.agency.browser.monitor import PageMonitor


class BrowserManager:
    """Central coordinator for all browser tools.

    Owns the shared rate limiter and Playwright lifecycle.
    """

    def __init__(self):
        self.rate_limiter = DomainRateLimiter()
        self.fetcher = WebFetcher()
        self.searcher = SearXNGSearcher()
        self.pool = PlaywrightPool()
        self.extractor = WebExtractor(self.pool)
        self.navigator = WebNavigator(self.pool)
        self.monitor = PageMonitor(self.fetcher)

    async def close(self) -> None:
        await self.fetcher.close()
        await self.searcher.close()
        await self.pool.close()
