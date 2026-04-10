"""Gmail API client — list, read, send emails via REST API."""

from __future__ import annotations

import base64
import logging
import re
from email.mime.text import MIMEText
from typing import Any

from core.auth.google_services import GoogleServiceBase

log = logging.getLogger(__name__)

GMAIL_API = "https://gmail.googleapis.com/gmail/v1/users/me"

# Strip HTML tags for plain-text fallback
_TAG_RE = re.compile(r"<[^>]+>")


class GmailClient(GoogleServiceBase):
    """Gmail API wrapper using httpx."""

    SERVICE_NAME = "gmail"

    def list_messages(
        self, query: str = "", max_results: int = 10, page_token: str | None = None,
    ) -> dict[str, Any]:
        """List/search emails. Returns message IDs + next page token."""
        params: dict[str, Any] = {"maxResults": min(max_results, 100)}
        if query:
            params["q"] = query
        if page_token:
            params["pageToken"] = page_token

        resp = self._request("GET", f"{GMAIL_API}/messages", params=params)
        data = resp.json()
        return {
            "messages": data.get("messages", []),
            "next_page_token": data.get("nextPageToken"),
            "result_size_estimate": data.get("resultSizeEstimate", 0),
        }

    def get_message(self, msg_id: str) -> dict[str, Any]:
        """Get a specific email with headers and body."""
        resp = self._request(
            "GET", f"{GMAIL_API}/messages/{msg_id}",
            params={"format": "full"},
        )
        data = resp.json()
        return self._parse_message(data)

    def send_message(
        self, to: str, subject: str, body: str, html: str | None = None,
    ) -> dict[str, Any]:
        """Send an email. Returns the sent message metadata."""
        if html:
            mime = MIMEText(html, "html")
        else:
            mime = MIMEText(body, "plain")
        mime["to"] = to
        mime["subject"] = subject

        raw = base64.urlsafe_b64encode(mime.as_bytes()).decode()
        resp = self._request(
            "POST", f"{GMAIL_API}/messages/send",
            json={"raw": raw},
        )
        return resp.json()

    def list_labels(self) -> list[dict[str, Any]]:
        """List Gmail labels."""
        resp = self._request("GET", f"{GMAIL_API}/labels")
        return resp.json().get("labels", [])

    @staticmethod
    def _parse_message(data: dict) -> dict[str, Any]:
        """Extract useful fields from Gmail API message format."""
        headers = {
            h["name"].lower(): h["value"]
            for h in data.get("payload", {}).get("headers", [])
        }
        # Extract body — prefer plain text, fall back to HTML stripped
        body = ""
        raw_mime = ""
        payload = data.get("payload", {})

        def _extract_body(part: dict) -> str:
            mime_type = part.get("mimeType", "")
            body_data = part.get("body", {}).get("data", "")
            if body_data:
                decoded = base64.urlsafe_b64decode(body_data).decode("utf-8", errors="replace")
                if mime_type == "text/plain":
                    return decoded
                if mime_type == "text/html":
                    return _TAG_RE.sub("", decoded)
            for sub in part.get("parts", []):
                result = _extract_body(sub)
                if result:
                    return result
            return ""

        body = _extract_body(payload)
        if payload.get("body", {}).get("data"):
            raw_mime = base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", errors="replace")

        return {
            "id": data.get("id"),
            "thread_id": data.get("threadId"),
            "subject": headers.get("subject", ""),
            "from": headers.get("from", ""),
            "to": headers.get("to", ""),
            "date": headers.get("date", ""),
            "snippet": data.get("snippet", ""),
            "body": body,
            "raw_mime": raw_mime,
            "label_ids": data.get("labelIds", []),
        }
