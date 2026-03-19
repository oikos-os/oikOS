"""Tests for Playwright browser lifecycle manager."""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from core.agency.browser.playwright_pool import PlaywrightPool


class TestPlaywrightPool:
    @pytest.mark.asyncio
    async def test_get_page_launches_browser(self):
        pool = PlaywrightPool()
        mock_pw = MagicMock()
        mock_browser = AsyncMock()
        mock_page = AsyncMock()
        mock_browser.new_page = AsyncMock(return_value=mock_page)
        mock_pw_instance = MagicMock()
        mock_pw_instance.chromium.launch = AsyncMock(return_value=mock_browser)
        with patch("core.agency.browser.playwright_pool.async_playwright") as mock_apw:
            mock_apw.return_value.__aenter__ = AsyncMock(return_value=mock_pw_instance)
            mock_apw.return_value.__aexit__ = AsyncMock(return_value=False)
            page = await pool.get_page()
        assert page is mock_page

    @pytest.mark.asyncio
    async def test_chromium_not_installed_raises(self):
        pool = PlaywrightPool()
        with patch("core.agency.browser.playwright_pool.async_playwright") as mock_apw:
            mock_pw_instance = MagicMock()
            mock_pw_instance.chromium.launch = AsyncMock(side_effect=Exception("Executable doesn't exist"))
            mock_apw.return_value.__aenter__ = AsyncMock(return_value=mock_pw_instance)
            mock_apw.return_value.__aexit__ = AsyncMock(return_value=False)
            with pytest.raises(RuntimeError, match="playwright install chromium"):
                await pool.get_page()

    @pytest.mark.asyncio
    async def test_close_shuts_down(self):
        pool = PlaywrightPool()
        mock_browser = AsyncMock()
        pool._browser = mock_browser
        pool._playwright_context = MagicMock()
        pool._playwright_context.__aexit__ = AsyncMock(return_value=False)
        await pool.close()
        mock_browser.close.assert_called_once()
