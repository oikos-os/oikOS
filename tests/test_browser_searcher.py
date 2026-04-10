"""Tests for SearXNG search client."""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from core.agency.browser.searcher import SearXNGSearcher

SAMPLE_RESPONSE = {
    "results": [
        {"title": "Result 1", "url": "https://example.com/1", "content": "Snippet 1"},
        {"title": "Result 2", "url": "https://example.com/2", "content": "Snippet 2"},
        {"title": "Result 3", "url": "https://example.com/3", "content": "Snippet 3"},
    ]
}


class TestSearXNGSearcher:
    @pytest.mark.asyncio
    async def test_search_returns_results(self):
        searcher = SearXNGSearcher()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = SAMPLE_RESPONSE
        with patch.object(searcher._client, "get", new_callable=AsyncMock, return_value=mock_response):
            result = await searcher.search("test query")
        assert result["query"] == "test query"
        assert len(result["results"]) == 3
        assert result["results"][0]["title"] == "Result 1"
        assert result["results"][0]["snippet"] == "Snippet 1"

    @pytest.mark.asyncio
    async def test_search_respects_count(self):
        searcher = SearXNGSearcher()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = SAMPLE_RESPONSE
        with patch.object(searcher._client, "get", new_callable=AsyncMock, return_value=mock_response):
            result = await searcher.search("test", count=2)
        assert len(result["results"]) == 2

    @pytest.mark.asyncio
    async def test_search_engine_down(self):
        searcher = SearXNGSearcher()
        with patch.object(searcher._client, "get", new_callable=AsyncMock, side_effect=Exception("refused")):
            result = await searcher.search("test")
        assert result["status"] == "error"
        assert "unavailable" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_search_passes_engines_param(self):
        searcher = SearXNGSearcher()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"results": []}
        with patch.object(searcher._client, "get", new_callable=AsyncMock, return_value=mock_response) as mock_get:
            await searcher.search("test", engines="google,duckduckgo")
        call_kwargs = mock_get.call_args
        assert "engines" in str(call_kwargs)

    @pytest.mark.asyncio
    async def test_search_empty_results(self):
        searcher = SearXNGSearcher()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"results": []}
        with patch.object(searcher._client, "get", new_callable=AsyncMock, return_value=mock_response):
            result = await searcher.search("obscure query")
        assert result["results"] == []
        assert result["count"] == 0
