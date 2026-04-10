"""Google Calendar API client — list, get, create events via REST API."""

from __future__ import annotations

import logging
from typing import Any

from core.auth.google_services import GoogleServiceBase

log = logging.getLogger(__name__)

CALENDAR_API = "https://www.googleapis.com/calendar/v3"


class CalendarClient(GoogleServiceBase):
    """Google Calendar API wrapper using httpx."""

    SERVICE_NAME = "calendar"

    def list_calendars(self) -> list[dict[str, Any]]:
        """List calendars the user has access to."""
        resp = self._request("GET", f"{CALENDAR_API}/users/me/calendarList")
        return resp.json().get("items", [])

    def list_events(
        self,
        calendar_id: str = "primary",
        time_min: str | None = None,
        time_max: str | None = None,
        max_results: int = 10,
        page_token: str | None = None,
    ) -> dict[str, Any]:
        """List events from a calendar. Times in RFC3339 format."""
        params: dict[str, Any] = {
            "maxResults": min(max_results, 100),
            "singleEvents": True,
            "orderBy": "startTime",
        }
        if time_min:
            params["timeMin"] = time_min
        if time_max:
            params["timeMax"] = time_max
        if page_token:
            params["pageToken"] = page_token

        resp = self._request("GET", f"{CALENDAR_API}/calendars/{calendar_id}/events", params=params)
        data = resp.json()
        return {
            "events": data.get("items", []),
            "next_page_token": data.get("nextPageToken"),
        }

    def get_event(self, calendar_id: str, event_id: str) -> dict[str, Any]:
        """Get a specific calendar event."""
        resp = self._request("GET", f"{CALENDAR_API}/calendars/{calendar_id}/events/{event_id}")
        return resp.json()

    def create_event(
        self,
        calendar_id: str = "primary",
        summary: str = "",
        start: str = "",
        end: str = "",
        description: str = "",
        location: str = "",
    ) -> dict[str, Any]:
        """Create a calendar event. Start/end in RFC3339 (e.g., '2026-03-25T10:00:00-04:00')."""
        event_body: dict[str, Any] = {
            "summary": summary,
            "start": {"dateTime": start},
            "end": {"dateTime": end},
        }
        if description:
            event_body["description"] = description
        if location:
            event_body["location"] = location

        resp = self._request("POST", f"{CALENDAR_API}/calendars/{calendar_id}/events", json=event_body)
        return resp.json()
