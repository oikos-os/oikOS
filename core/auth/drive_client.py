"""Google Drive API client — list, search, download files via REST API."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from core.auth.google_services import GoogleServiceBase

log = logging.getLogger(__name__)

DRIVE_API = "https://www.googleapis.com/drive/v3"


class DriveClient(GoogleServiceBase):
    """Google Drive API wrapper using httpx."""

    SERVICE_NAME = "drive"

    def list_files(
        self,
        query: str | None = None,
        max_results: int = 10,
        page_token: str | None = None,
    ) -> dict[str, Any]:
        """List files in Drive. Optional query uses Drive search syntax."""
        params: dict[str, Any] = {
            "pageSize": min(max_results, 100),
            "fields": "nextPageToken, files(id, name, mimeType, size, modifiedTime, owners)",
        }
        if query:
            params["q"] = query
        if page_token:
            params["pageToken"] = page_token

        resp = self._request("GET", f"{DRIVE_API}/files", params=params)
        data = resp.json()
        return {
            "files": data.get("files", []),
            "next_page_token": data.get("nextPageToken"),
        }

    def search_files(self, query: str, max_results: int = 10) -> dict[str, Any]:
        """Search files by name. Wraps list_files with name contains query."""
        escaped = query.replace("'", "\\'")
        return self.list_files(query=f"name contains '{escaped}'", max_results=max_results)

    def get_file_metadata(self, file_id: str) -> dict[str, Any]:
        """Get metadata for a specific file."""
        resp = self._request(
            "GET", f"{DRIVE_API}/files/{file_id}",
            params={"fields": "id, name, mimeType, size, modifiedTime, owners, webViewLink, parents"},
        )
        return resp.json()

    def download_file(self, file_id: str, destination: str | None = None) -> dict[str, Any]:
        """Download a file to staging/. Returns file path and metadata."""
        from core.interface.config import PROJECT_ROOT

        # Get metadata first
        meta = self.get_file_metadata(file_id)
        # Sanitize filename — strip directory components to prevent path traversal
        raw_name = meta.get("name", file_id)
        filename = Path(raw_name).name or file_id

        # Determine download path
        staging_dir = PROJECT_ROOT / "staging"
        staging_dir.mkdir(exist_ok=True)
        if destination:
            dest = Path(destination)
        else:
            dest = staging_dir / filename
            # Verify resolved path is under staging (defense against traversal via API filename)
            if not dest.resolve().is_relative_to(staging_dir.resolve()):
                from core.auth.google_services import GoogleAPIError
                raise GoogleAPIError(self.SERVICE_NAME, 0, "Invalid filename — path traversal blocked")

        # Download content
        resp = self._request(
            "GET", f"{DRIVE_API}/files/{file_id}",
            params={"alt": "media"},
        )
        dest.write_bytes(resp.content)
        log.info("Downloaded %s to %s (%d bytes)", filename, dest, len(resp.content))

        return {
            "file_id": file_id,
            "name": filename,
            "path": str(dest),
            "size_bytes": len(resp.content),
            "mime_type": meta.get("mimeType", ""),
        }
