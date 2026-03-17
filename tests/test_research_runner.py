"""Tests for research runner — search → fetch → summarize → stage pipeline."""

import json
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from core.agency.research.runner import ResearchRunner


def _mock_search_result(urls):
    return {"results": [{"url": u, "title": f"Title for {u}", "snippet": "..."} for u in urls], "count": len(urls)}


def _mock_fetch_result(url):
    return {"url": url, "title": "Page Title", "content": f"Content from {url} " * 50, "content_tokens": 200, "truncated": False}


def _mock_ollama_result(text):
    return {"response": f"Summary: {text[:50]}...", "model": "qwen2.5:7b", "eval_count": 50}


class TestResearchRunner:
    @pytest.mark.asyncio
    async def test_run_single_topic(self, tmp_path):
        runner = ResearchRunner(staging_dir=tmp_path)
        with patch("core.agency.research.runner.web_search", new_callable=AsyncMock, return_value=_mock_search_result(["https://example.com/1"])), \
             patch("core.agency.research.runner.web_fetch", new_callable=AsyncMock, return_value=_mock_fetch_result("https://example.com/1")), \
             patch("core.agency.research.runner.generate_local", return_value=_mock_ollama_result("test")), \
             patch("core.agency.research.runner.is_duplicate", return_value=False):
            result = await runner.run_topic("test topic", max_results=1)
        assert result["staged"] is True
        staged_files = list(tmp_path.glob("*.md"))
        assert len(staged_files) == 1

    @pytest.mark.asyncio
    async def test_staged_file_has_frontmatter(self, tmp_path):
        runner = ResearchRunner(staging_dir=tmp_path)
        with patch("core.agency.research.runner.web_search", new_callable=AsyncMock, return_value=_mock_search_result(["https://example.com/1"])), \
             patch("core.agency.research.runner.web_fetch", new_callable=AsyncMock, return_value=_mock_fetch_result("https://example.com/1")), \
             patch("core.agency.research.runner.generate_local", return_value=_mock_ollama_result("test")), \
             patch("core.agency.research.runner.is_duplicate", return_value=False):
            await runner.run_topic("test topic", max_results=1)
        content = list(tmp_path.glob("*.md"))[0].read_text()
        assert "---" in content
        assert "topic: test topic" in content
        assert "sources:" in content
        assert "tier: semantic" in content
        assert "domain: RESEARCH" in content

    @pytest.mark.asyncio
    async def test_dedup_skips_staging(self, tmp_path):
        runner = ResearchRunner(staging_dir=tmp_path)
        with patch("core.agency.research.runner.web_search", new_callable=AsyncMock, return_value=_mock_search_result(["https://example.com/1"])), \
             patch("core.agency.research.runner.web_fetch", new_callable=AsyncMock, return_value=_mock_fetch_result("https://example.com/1")), \
             patch("core.agency.research.runner.generate_local", return_value=_mock_ollama_result("test")), \
             patch("core.agency.research.runner.is_duplicate", return_value=True):
            result = await runner.run_topic("duplicate topic", max_results=1)
        assert result["staged"] is False
        assert result["skipped_duplicate"] is True

    @pytest.mark.asyncio
    async def test_search_failure_returns_error(self, tmp_path):
        runner = ResearchRunner(staging_dir=tmp_path)
        with patch("core.agency.research.runner.web_search", new_callable=AsyncMock, return_value={"status": "error", "message": "unavailable"}):
            result = await runner.run_topic("topic", max_results=1)
        assert result["staged"] is False
        assert "error" in result

    @pytest.mark.asyncio
    async def test_fetch_failure_skips_url(self, tmp_path):
        runner = ResearchRunner(staging_dir=tmp_path)
        fail_fetch = {"status": "error", "message": "Connection failed"}
        ok_fetch = _mock_fetch_result("https://example.com/2")
        with patch("core.agency.research.runner.web_search", new_callable=AsyncMock, return_value=_mock_search_result(["https://bad.com", "https://example.com/2"])), \
             patch("core.agency.research.runner.web_fetch", new_callable=AsyncMock, side_effect=[fail_fetch, ok_fetch]), \
             patch("core.agency.research.runner.generate_local", return_value=_mock_ollama_result("test")), \
             patch("core.agency.research.runner.is_duplicate", return_value=False):
            result = await runner.run_topic("topic", max_results=2)
        assert result["staged"] is True
        content = list(tmp_path.glob("*.md"))[0].read_text()
        assert "https://example.com/2" in content
        assert "https://bad.com" not in content

    @pytest.mark.asyncio
    async def test_ollama_down_returns_error(self, tmp_path):
        runner = ResearchRunner(staging_dir=tmp_path)
        with patch("core.agency.research.runner.web_search", new_callable=AsyncMock, return_value=_mock_search_result(["https://example.com/1"])), \
             patch("core.agency.research.runner.web_fetch", new_callable=AsyncMock, return_value=_mock_fetch_result("https://example.com/1")), \
             patch("core.agency.research.runner.generate_local", side_effect=ConnectionError("connection refused")):
            result = await runner.run_topic("topic", max_results=1)
        assert result["staged"] is False
        assert "ollama" in result.get("error", "").lower() or "error" in result

    @pytest.mark.asyncio
    async def test_token_budget_tracking(self, tmp_path):
        runner = ResearchRunner(staging_dir=tmp_path)
        with patch("core.agency.research.runner.web_search", new_callable=AsyncMock, return_value=_mock_search_result(["https://example.com/1"])), \
             patch("core.agency.research.runner.web_fetch", new_callable=AsyncMock, return_value=_mock_fetch_result("https://example.com/1")), \
             patch("core.agency.research.runner.generate_local", return_value=_mock_ollama_result("test")), \
             patch("core.agency.research.runner.is_duplicate", return_value=False):
            result = await runner.run_topic("topic", max_results=1)
        assert result["tokens_used"] > 0
