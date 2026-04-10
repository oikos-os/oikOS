"""Async API client for the oikOS TUI."""
from __future__ import annotations

import json
import os

import httpx

def scopes_to_services(scopes: list[str]) -> list[str]:
    """Map Google OAuth scope URIs to human-readable service names."""
    services = []
    for scope in scopes:
        s = scope.lower()
        if "gmail" in s and "Gmail" not in services:
            services.append("Gmail")
        elif "calendar" in s and "Calendar" not in services:
            services.append("Calendar")
        elif "drive" in s and "Drive" not in services:
            services.append("Drive")
    return services


class OikOSClient:
    """Thin async wrapper around the oikOS FastAPI backend."""

    def __init__(
        self,
        base_url: str | None = None,
        transport: httpx.AsyncBaseTransport | httpx.BaseTransport | None = None,
    ):
        if base_url is None:
            from core.interface.settings import get_setting
            base_url = f"http://127.0.0.1:{get_setting('api_port')}"
        self.port = int(base_url.rsplit(":", 1)[-1])
        api_key = os.environ.get("OIKOS_API_KEY")
        headers = {"X-API-Key": api_key} if api_key else {}
        kwargs: dict = {"base_url": base_url, "headers": headers, "timeout": 5.0}
        if transport is not None:
            kwargs["transport"] = transport
        self._client = httpx.AsyncClient(**kwargs)

    async def _get(self, path: str, fallback=None):
        """GET with error handling — returns fallback on failure."""
        if fallback is None:
            fallback = {}
        try:
            r = await self._client.get(path)
            if r.status_code == 200:
                return r.json()
        except (httpx.ConnectError, httpx.TimeoutException):
            pass
        return fallback

    async def is_reachable(self) -> bool:
        try:
            r = await self._client.get("/api/health")
            return r.status_code == 200
        except (httpx.ConnectError, httpx.TimeoutException):
            return False

    async def state(self) -> dict:
        return await self._get("/api/state")

    async def rooms(self) -> list[dict]:
        return await self._get("/api/rooms", fallback=[])

    async def active_room(self) -> dict:
        return await self._get("/api/rooms/active", fallback={"id": "home", "name": "Home"})

    async def models(self) -> dict:
        return await self._get("/api/models", fallback={})

    async def vault_stats(self) -> dict:
        return await self._get("/api/vault/stats", fallback={"total_rows": 0, "unique_files": 0})

    async def search(self, query: str, limit: int = 10) -> list[dict]:
        try:
            r = await self._client.get("/api/search", params={"q": query, "limit": limit})
            if r.status_code == 200:
                return r.json().get("results", [])
        except (httpx.ConnectError, httpx.TimeoutException):
            pass
        return []

    async def settings(self) -> dict:
        return await self._get("/api/settings")

    async def claude_status(self) -> dict:
        return await self._get("/api/auth/claude/status", fallback={"connected": False})

    async def google_status(self) -> dict:
        return await self._get("/api/auth/google/status", fallback={"connected": False})

    async def tools(self) -> dict:
        return await self._get("/api/agents/tools", fallback={"total": 0, "toolsets": {}})

    async def events(self, limit: int = 20) -> list[dict]:
        return await self._get(f"/api/events?limit={limit}", fallback=[])

    async def switch_room(self, room_id: str) -> dict:
        """POST /api/rooms/switch with JSON body."""
        try:
            r = await self._client.post("/api/rooms/switch", json={"room_id": room_id})
            if r.status_code == 200:
                return r.json()
        except (httpx.ConnectError, httpx.TimeoutException):
            pass
        return {}

    async def update_setting(self, key: str, value) -> dict:
        """PUT /api/settings with JSON body."""
        try:
            r = await self._client.put("/api/settings", json={"key": key, "value": value})
            if r.status_code == 200:
                return r.json()
        except (httpx.ConnectError, httpx.TimeoutException):
            pass
        return {}

    async def chat_stream(self, query: str, model: str | None = None):
        """Stream chat response via SSE. Yields dicts: {"delta": str} or {"done": True, ...}."""
        payload: dict = {"query": query}
        if model:
            payload["model"] = model
        async with self._client.stream(
            "POST", "/api/chat", json=payload, timeout=120.0,
        ) as response:
            if response.status_code != 200:
                yield {"done": True, "error": f"HTTP {response.status_code}"}
                return
            async for line in response.aiter_lines():
                if line.startswith("data: "):
                    try:
                        yield json.loads(line[6:])
                    except json.JSONDecodeError:
                        continue

    async def pending_approvals(self) -> list[dict]:
        """GET /api/approvals — returns list of pending approval requests."""
        data = await self._get("/api/approvals", fallback={"pending": []})
        return data.get("pending", [])

    async def pending_notifications(self, since: float | None = None) -> list[dict]:
        """GET /api/notifications/pending — returns list of pending notifications.

        Use `since` to paginate forward by timestamp.
        """
        path = "/api/notifications/pending"
        if since is not None:
            path += f"?since={since}"
        data = await self._get(path, fallback={"pending": []})
        return data.get("pending", [])

    async def approval_approve(self, proposal_id: str) -> dict:
        """POST /api/approvals/{id}/approve."""
        try:
            r = await self._client.post(f"/api/approvals/{proposal_id}/approve")
            if r.status_code == 200:
                return r.json()
        except (httpx.ConnectError, httpx.TimeoutException):
            pass
        return {}

    async def approval_reject(self, proposal_id: str, reason: str | None = None) -> dict:
        """POST /api/approvals/{id}/reject."""
        body = {"reason": reason} if reason else None
        try:
            r = await self._client.post(f"/api/approvals/{proposal_id}/reject", json=body)
            if r.status_code == 200:
                return r.json()
        except (httpx.ConnectError, httpx.TimeoutException):
            pass
        return {}

    async def approval_dismiss(self, proposal_id: str) -> dict:
        """DELETE /api/approvals/{id}."""
        try:
            r = await self._client.delete(f"/api/approvals/{proposal_id}")
            if r.status_code == 200:
                return r.json()
        except (httpx.ConnectError, httpx.TimeoutException):
            pass
        return {}

    async def close(self) -> None:
        await self._client.aclose()
