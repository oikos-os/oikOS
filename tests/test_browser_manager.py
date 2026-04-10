"""Tests for BrowserManager — central coordinator."""

import pytest
from unittest.mock import AsyncMock, MagicMock
from core.agency.browser import BrowserManager


class TestBrowserManager:
    def test_singleton_rate_limiter(self):
        mgr = BrowserManager()
        assert mgr.rate_limiter is mgr.rate_limiter

    def test_has_fetcher(self):
        mgr = BrowserManager()
        assert mgr.fetcher is not None

    def test_has_searcher(self):
        mgr = BrowserManager()
        assert mgr.searcher is not None

    def test_has_pool(self):
        mgr = BrowserManager()
        assert mgr.pool is not None

    def test_has_extractor(self):
        mgr = BrowserManager()
        assert mgr.extractor is not None

    def test_has_navigator(self):
        mgr = BrowserManager()
        assert mgr.navigator is not None

    def test_has_monitor(self):
        mgr = BrowserManager()
        assert mgr.monitor is not None

    @pytest.mark.asyncio
    async def test_close_shuts_all_down(self):
        mgr = BrowserManager()
        mgr.fetcher = MagicMock()
        mgr.fetcher.close = AsyncMock()
        mgr.searcher = MagicMock()
        mgr.searcher.close = AsyncMock()
        mgr.pool = MagicMock()
        mgr.pool.close = AsyncMock()
        await mgr.close()
        mgr.fetcher.close.assert_called_once()
        mgr.searcher.close.assert_called_once()
        mgr.pool.close.assert_called_once()
