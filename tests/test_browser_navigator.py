"""Tests for multi-step browser automation."""

import pytest
from unittest.mock import AsyncMock, MagicMock
from core.agency.browser.navigator import WebNavigator


class TestWebNavigator:
    @pytest.mark.asyncio
    async def test_click_action(self):
        mock_pool = MagicMock()
        mock_page = AsyncMock()
        mock_page.goto = AsyncMock()
        mock_page.click = AsyncMock()
        mock_page.close = AsyncMock()
        mock_pool.get_page = AsyncMock(return_value=mock_page)

        nav = WebNavigator(mock_pool)
        result = await nav.navigate("https://example.com", [{"type": "click", "selector": "#btn"}])
        assert result["steps_completed"] == 1
        assert result["results"][0]["status"] == "ok"

    @pytest.mark.asyncio
    async def test_fill_action(self):
        mock_pool = MagicMock()
        mock_page = AsyncMock()
        mock_page.goto = AsyncMock()
        mock_page.fill = AsyncMock()
        mock_page.close = AsyncMock()
        mock_pool.get_page = AsyncMock(return_value=mock_page)

        nav = WebNavigator(mock_pool)
        result = await nav.navigate("https://example.com", [{"type": "fill", "selector": "#input", "value": "hello"}])
        assert result["steps_completed"] == 1
        mock_page.fill.assert_called_once_with("#input", "hello")

    @pytest.mark.asyncio
    async def test_wait_action(self):
        mock_pool = MagicMock()
        mock_page = AsyncMock()
        mock_page.goto = AsyncMock()
        mock_page.wait_for_selector = AsyncMock()
        mock_page.close = AsyncMock()
        mock_pool.get_page = AsyncMock(return_value=mock_page)

        nav = WebNavigator(mock_pool)
        result = await nav.navigate("https://example.com", [{"type": "wait", "selector": ".loaded"}])
        assert result["results"][0]["status"] == "ok"

    @pytest.mark.asyncio
    async def test_multiple_actions_sequential(self):
        mock_pool = MagicMock()
        mock_page = AsyncMock()
        mock_page.goto = AsyncMock()
        mock_page.click = AsyncMock()
        mock_page.fill = AsyncMock()
        mock_page.close = AsyncMock()
        mock_pool.get_page = AsyncMock(return_value=mock_page)

        nav = WebNavigator(mock_pool)
        actions = [
            {"type": "fill", "selector": "#user", "value": "test"},
            {"type": "click", "selector": "#submit"},
        ]
        result = await nav.navigate("https://example.com", actions)
        assert result["steps_completed"] == 2

    @pytest.mark.asyncio
    async def test_unknown_action_type_returns_error(self):
        mock_pool = MagicMock()
        mock_page = AsyncMock()
        mock_page.goto = AsyncMock()
        mock_page.close = AsyncMock()
        mock_pool.get_page = AsyncMock(return_value=mock_page)

        nav = WebNavigator(mock_pool)
        result = await nav.navigate("https://example.com", [{"type": "invalid"}])
        assert result["results"][0]["status"] == "error"

    @pytest.mark.asyncio
    async def test_action_failure_continues(self):
        mock_pool = MagicMock()
        mock_page = AsyncMock()
        mock_page.goto = AsyncMock()
        mock_page.click = AsyncMock(side_effect=Exception("element not found"))
        mock_page.fill = AsyncMock()
        mock_page.close = AsyncMock()
        mock_pool.get_page = AsyncMock(return_value=mock_page)

        nav = WebNavigator(mock_pool)
        actions = [
            {"type": "click", "selector": "#missing"},
            {"type": "fill", "selector": "#input", "value": "test"},
        ]
        result = await nav.navigate("https://example.com", actions)
        assert result["steps_completed"] == 2
        assert result["results"][0]["status"] == "error"
        assert result["results"][1]["status"] == "ok"
