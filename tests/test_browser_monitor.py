"""Tests for page change monitor."""

import json
import hashlib
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from core.agency.browser.monitor import PageMonitor


class TestPageMonitor:
    @pytest.mark.asyncio
    async def test_first_check_returns_changed_false(self, tmp_path):
        mock_fetcher = MagicMock()
        mock_fetcher.fetch = AsyncMock(return_value={"content": "hello world", "title": "Test"})
        monitor = PageMonitor(mock_fetcher, state_path=tmp_path / "state.json")
        result = await monitor.check("https://example.com")
        assert result["changed"] is False
        assert result["diff_summary"] is None

    @pytest.mark.asyncio
    async def test_no_change_returns_false(self, tmp_path):
        mock_fetcher = MagicMock()
        mock_fetcher.fetch = AsyncMock(return_value={"content": "hello world", "title": "Test"})
        monitor = PageMonitor(mock_fetcher, state_path=tmp_path / "state.json")
        await monitor.check("https://example.com")
        result = await monitor.check("https://example.com")
        assert result["changed"] is False

    @pytest.mark.asyncio
    async def test_content_change_detected(self, tmp_path):
        mock_fetcher = MagicMock()
        mock_fetcher.fetch = AsyncMock(return_value={"content": "version 1", "title": "Test"})
        monitor = PageMonitor(mock_fetcher, state_path=tmp_path / "state.json")
        await monitor.check("https://example.com")

        mock_fetcher.fetch = AsyncMock(return_value={"content": "version 2 with more", "title": "Test"})
        result = await monitor.check("https://example.com")
        assert result["changed"] is True
        assert "delta=" in result["diff_summary"]

    @pytest.mark.asyncio
    async def test_state_persists_to_file(self, tmp_path):
        mock_fetcher = MagicMock()
        mock_fetcher.fetch = AsyncMock(return_value={"content": "persistent", "title": "T"})
        state_file = tmp_path / "state.json"
        monitor = PageMonitor(mock_fetcher, state_path=state_file)
        await monitor.check("https://example.com")
        assert state_file.exists()
        state = json.loads(state_file.read_text())
        assert "https://example.com" in state

    @pytest.mark.asyncio
    async def test_fetch_error_returns_error(self, tmp_path):
        mock_fetcher = MagicMock()
        mock_fetcher.fetch = AsyncMock(return_value={"status": "error", "message": "Connection failed"})
        monitor = PageMonitor(mock_fetcher, state_path=tmp_path / "state.json")
        result = await monitor.check("https://down.example.com")
        assert result["status"] == "error"
