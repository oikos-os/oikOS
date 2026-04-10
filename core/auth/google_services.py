"""Google service client base — shared HTTP + token refresh logic."""

from __future__ import annotations

import logging
from typing import Any

import httpx

log = logging.getLogger(__name__)

GOOGLE_API_BASE = "https://www.googleapis.com"


class GoogleAPIError(Exception):
    """Error from a Google API call."""

    def __init__(self, service: str, status_code: int, message: str):
        self.service = service
        self.status_code = status_code
        self.message = message
        super().__init__(f"[{service}] HTTP {status_code}: {message}")


class GoogleServiceBase:
    """Base class for Google API service clients.

    Uses httpx for HTTP, auto-refreshes on 401, retries once.
    """

    SERVICE_NAME: str = "google"

    def __init__(self) -> None:
        self._client = httpx.Client(timeout=30.0)

    def _get_token(self) -> str:
        """Get a valid Google access token, refreshing if needed."""
        from core.auth.google_oauth import get_google_tokens

        tokens = get_google_tokens()
        if tokens is None:
            raise GoogleAPIError(
                self.SERVICE_NAME, 0,
                "Google not connected. Connect via Settings > Connected Accounts.",
            )
        return tokens.access_token

    def _request(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
        data: Any = None,
        headers: dict[str, str] | None = None,
        stream: bool = False,
    ) -> httpx.Response:
        """Make an authenticated Google API request with auto-refresh on 401."""
        token = self._get_token()
        req_headers = {"Authorization": f"Bearer {token}"}
        if headers:
            req_headers.update(headers)

        resp = self._client.request(
            method, url, params=params, json=json, content=data, headers=req_headers,
        )

        # Auto-refresh on 401 and retry once
        if resp.status_code == 401:
            from core.auth.google_oauth import refresh_google_token

            if refresh_google_token():
                token = self._get_token()
                req_headers["Authorization"] = f"Bearer {token}"
                resp = self._client.request(
                    method, url, params=params, json=json, content=data, headers=req_headers,
                )

        if resp.status_code >= 400:
            try:
                error_detail = resp.json().get("error", {}).get("message", resp.text[:200])
            except Exception:
                error_detail = resp.text[:200]
            raise GoogleAPIError(self.SERVICE_NAME, resp.status_code, error_detail)

        return resp

    def close(self) -> None:
        self._client.close()
