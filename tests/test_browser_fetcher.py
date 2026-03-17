"""Tests for Layer 1 web fetcher — httpx + readability."""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from core.agency.browser.fetcher import WebFetcher


SAMPLE_HTML = """
<html><head><title>Test Page</title></head>
<body>
<div id="content">
<h1>Hello World</h1>
<p>This is a test paragraph with enough content to be extracted by readability.</p>
<p>Another paragraph to ensure readability has enough to work with in extraction.</p>
</div>
</body></html>
"""


class TestWebFetcher:
    @pytest.mark.asyncio
    async def test_fetch_returns_expected_keys(self):
        fetcher = WebFetcher()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = SAMPLE_HTML
        mock_response.url = "https://example.com/page"
        with patch.object(fetcher._client, "get", new_callable=AsyncMock, return_value=mock_response):
            result = await fetcher.fetch("https://example.com/page")
        assert "url" in result
        assert "title" in result
        assert "content" in result
        assert "content_tokens" in result
        assert "truncated" in result

    @pytest.mark.asyncio
    async def test_fetch_truncates_to_max_tokens(self):
        fetcher = WebFetcher()
        long_html = "<html><body><p>" + "word " * 10000 + "</p></body></html>"
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = long_html
        mock_response.url = "https://example.com"
        with patch.object(fetcher._client, "get", new_callable=AsyncMock, return_value=mock_response):
            result = await fetcher.fetch("https://example.com", max_tokens=100)
        assert result["truncated"] is True
        assert result["content_tokens"] <= 100

    @pytest.mark.asyncio
    async def test_fetch_connection_error(self):
        fetcher = WebFetcher()
        with patch.object(fetcher._client, "get", new_callable=AsyncMock, side_effect=Exception("connection refused")):
            result = await fetcher.fetch("https://down.example.com")
        assert result["status"] == "error"
        assert "Connection failed" in result["message"]

    @pytest.mark.asyncio
    async def test_fetch_timeout(self):
        import httpx
        fetcher = WebFetcher()
        with patch.object(fetcher._client, "get", new_callable=AsyncMock, side_effect=httpx.TimeoutException("timeout")):
            result = await fetcher.fetch("https://slow.example.com")
        assert result["status"] == "error"
        assert "timed out" in result["message"]

    @pytest.mark.asyncio
    async def test_fetch_non_200_returns_error(self):
        fetcher = WebFetcher()
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_response.url = "https://example.com/missing"
        with patch.object(fetcher._client, "get", new_callable=AsyncMock, return_value=mock_response):
            result = await fetcher.fetch("https://example.com/missing")
        assert result["status"] == "error"
