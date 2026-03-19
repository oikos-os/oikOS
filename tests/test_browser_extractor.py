"""Tests for Playwright element extractor."""

import pytest
from unittest.mock import AsyncMock, MagicMock
from core.agency.browser.extractor import WebExtractor


class TestWebExtractor:
    @pytest.mark.asyncio
    async def test_extract_css_selector(self):
        mock_pool = MagicMock()
        mock_page = AsyncMock()
        mock_element = AsyncMock()
        mock_element.inner_text = AsyncMock(return_value="Hello")
        mock_element.inner_html = AsyncMock(return_value="<b>Hello</b>")
        mock_element.evaluate = AsyncMock(return_value="B")
        mock_page.query_selector_all = AsyncMock(return_value=[mock_element])
        mock_page.goto = AsyncMock()
        mock_page.close = AsyncMock()
        mock_pool.get_page = AsyncMock(return_value=mock_page)

        extractor = WebExtractor(mock_pool)
        result = await extractor.extract("https://example.com", "b", "css")
        assert result["count"] == 1
        assert result["matches"][0]["text"] == "Hello"

    @pytest.mark.asyncio
    async def test_extract_no_matches(self):
        mock_pool = MagicMock()
        mock_page = AsyncMock()
        mock_page.query_selector_all = AsyncMock(return_value=[])
        mock_page.goto = AsyncMock()
        mock_page.close = AsyncMock()
        mock_pool.get_page = AsyncMock(return_value=mock_page)

        extractor = WebExtractor(mock_pool)
        result = await extractor.extract("https://example.com", ".nonexistent", "css")
        assert result["count"] == 0
        assert result["matches"] == []

    @pytest.mark.asyncio
    async def test_extract_xpath(self):
        mock_pool = MagicMock()
        mock_page = AsyncMock()
        mock_element = AsyncMock()
        mock_element.inner_text = AsyncMock(return_value="XPath Hit")
        mock_element.inner_html = AsyncMock(return_value="XPath Hit")
        mock_element.evaluate = AsyncMock(return_value="P")
        mock_page.query_selector_all = AsyncMock(return_value=[mock_element])
        mock_page.goto = AsyncMock()
        mock_page.close = AsyncMock()
        mock_pool.get_page = AsyncMock(return_value=mock_page)

        extractor = WebExtractor(mock_pool)
        result = await extractor.extract("https://example.com", "//p", "xpath")
        assert result["count"] == 1

    @pytest.mark.asyncio
    async def test_extract_page_closed_after_use(self):
        mock_pool = MagicMock()
        mock_page = AsyncMock()
        mock_page.query_selector_all = AsyncMock(return_value=[])
        mock_page.goto = AsyncMock()
        mock_page.close = AsyncMock()
        mock_pool.get_page = AsyncMock(return_value=mock_page)

        extractor = WebExtractor(mock_pool)
        await extractor.extract("https://example.com", "div", "css")
        mock_page.close.assert_called_once()
