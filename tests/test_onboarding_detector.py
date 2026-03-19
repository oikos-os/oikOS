import pytest
from unittest.mock import patch, AsyncMock, MagicMock
import httpx


@pytest.fixture
def mock_client():
    """Create a mock httpx.AsyncClient."""
    client = MagicMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    return client


class TestBackendDetector:
    @pytest.mark.asyncio
    async def test_detect_ollama(self, mock_client):
        mock_client.get = AsyncMock(return_value=httpx.Response(200, json={"models": [
            {"name": "qwen2.5:14b", "size": 9_200_000_000},
            {"name": "qwen2.5:7b", "size": 4_400_000_000},
        ]}))
        with patch("core.onboarding.detector.httpx.AsyncClient", return_value=mock_client):
            from core.onboarding.detector import BackendDetector
            results = await BackendDetector().scan()
        ollama = [r for r in results if r["backend"] == "ollama"]
        assert len(ollama) == 1
        assert len(ollama[0]["models"]) == 2

    @pytest.mark.asyncio
    async def test_detect_nothing(self, mock_client):
        mock_client.get = AsyncMock(side_effect=httpx.ConnectError("refused"))
        with patch("core.onboarding.detector.httpx.AsyncClient", return_value=mock_client):
            from core.onboarding.detector import BackendDetector
            results = await BackendDetector().scan()
        assert results == []

    @pytest.mark.asyncio
    async def test_timeout_handling(self, mock_client):
        mock_client.get = AsyncMock(side_effect=httpx.ReadTimeout("timeout"))
        with patch("core.onboarding.detector.httpx.AsyncClient", return_value=mock_client):
            from core.onboarding.detector import BackendDetector
            results = await BackendDetector(timeout=0.5).scan()
        assert results == []

    @pytest.mark.asyncio
    async def test_partial_detection(self, mock_client):
        async def selective_get(url, **kwargs):
            if "11434" in url:
                return httpx.Response(200, json={"models": [{"name": "qwen2.5:7b", "size": 4_400_000_000}]})
            raise httpx.ConnectError("refused")
        mock_client.get = AsyncMock(side_effect=selective_get)
        with patch("core.onboarding.detector.httpx.AsyncClient", return_value=mock_client):
            from core.onboarding.detector import BackendDetector
            results = await BackendDetector().scan()
        assert len(results) == 1
        assert results[0]["backend"] == "ollama"

    def test_sync_wrapper(self):
        with patch("core.onboarding.detector.BackendDetector.scan", new_callable=AsyncMock, return_value=[]):
            from core.onboarding.detector import detect_backends
            results = detect_backends()
        assert results == []
