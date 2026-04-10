"""Tests for the TUI API client."""
from __future__ import annotations

import json

import httpx
import pytest

from core.interface.tui.client import OikOSClient


def _make_transport(responses: dict):
    """Create a mock httpx transport from a path->response dict."""
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path in responses:
            return httpx.Response(200, json=responses[path])
        return httpx.Response(404, json={"detail": "not found"})
    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_is_reachable_when_server_up(mock_api_responses):
    transport = _make_transport(mock_api_responses)
    client = OikOSClient(transport=transport)
    assert await client.is_reachable() is True
    await client.close()


@pytest.mark.asyncio
async def test_is_reachable_when_server_down():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")
    transport = httpx.MockTransport(handler)
    client = OikOSClient(transport=transport)
    assert await client.is_reachable() is False
    await client.close()


@pytest.mark.asyncio
async def test_state_returns_data(mock_api_responses):
    transport = _make_transport(mock_api_responses)
    client = OikOSClient(transport=transport)
    state = await client.state()
    assert state["version"] == "0.0.8"
    assert state["uptime"] == 3600.0
    await client.close()


@pytest.mark.asyncio
async def test_rooms_returns_list(mock_api_responses):
    transport = _make_transport(mock_api_responses)
    client = OikOSClient(transport=transport)
    rooms = await client.rooms()
    assert len(rooms) == 2
    assert rooms[0]["id"] == "home"
    await client.close()


@pytest.mark.asyncio
async def test_vault_stats(mock_api_responses):
    transport = _make_transport(mock_api_responses)
    client = OikOSClient(transport=transport)
    stats = await client.vault_stats()
    assert stats["unique_files"] == 132
    await client.close()


@pytest.mark.asyncio
async def test_api_key_header(mock_api_responses, monkeypatch):
    monkeypatch.setenv("OIKOS_API_KEY", "test-key-123")
    transport = _make_transport(mock_api_responses)
    client = OikOSClient(transport=transport)
    # Access internal client to verify headers
    assert client._client.headers.get("x-api-key") == "test-key-123"
    await client.close()


@pytest.mark.asyncio
async def test_fallback_on_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"detail": "internal error"})
    transport = httpx.MockTransport(handler)
    client = OikOSClient(transport=transport)
    # Should return fallback empty dict, not raise
    state = await client.state()
    assert state == {}
    await client.close()


@pytest.mark.asyncio
async def test_chat_stream_parses_sse():
    """chat_stream should yield parsed dicts from SSE data: lines."""
    sse_body = (
        'data: {"delta": "Hello"}\n\n'
        'data: {"delta": " world"}\n\n'
        'data: {"done": true, "model": "qwen2.5:14b"}\n\n'
    )
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=sse_body.encode(), headers={"content-type": "text/event-stream"})
    transport = httpx.MockTransport(handler)
    client = OikOSClient(transport=transport)
    chunks = []
    async for chunk in client.chat_stream("test query"):
        chunks.append(chunk)
    await client.close()
    assert len(chunks) == 3
    assert chunks[0] == {"delta": "Hello"}
    assert chunks[1] == {"delta": " world"}
    assert chunks[2]["done"] is True
    assert chunks[2]["model"] == "qwen2.5:14b"
