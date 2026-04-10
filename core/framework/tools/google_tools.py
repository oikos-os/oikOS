"""Google service MCP tools — Gmail, Calendar, Drive."""

from __future__ import annotations

from core.framework import oikos_tool, PrivacyTier, AutonomyLevel


def _check_google() -> None:
    """Raise if Google OAuth is not connected."""
    from core.auth.google_oauth import is_google_connected

    if not is_google_connected():
        raise RuntimeError(
            "Google not connected. Connect via Settings > Connected Accounts > Sign in with Google."
        )


# ── Gmail ────────────────────────────────────────────────────────────

@oikos_tool(
    name="oikos_google_gmail_list",
    description="Search or list Gmail messages",
    privacy=PrivacyTier.SENSITIVE,
    autonomy=AutonomyLevel.SAFE,
    toolset="google",
    concurrent_safe=True,
    read_only=True,
    search_hint="gmail email list search inbox messages",
    group="google",
)
def gmail_list(query: str = "", max_results: int = 10, page_token: str | None = None) -> dict:
    _check_google()
    from core.auth.gmail_client import GmailClient

    client = GmailClient()
    return client.list_messages(query=query, max_results=max_results, page_token=page_token)


@oikos_tool(
    name="oikos_google_gmail_read",
    description="Read a specific Gmail message by ID",
    privacy=PrivacyTier.SENSITIVE,
    autonomy=AutonomyLevel.SAFE,
    toolset="google",
    concurrent_safe=True,
    read_only=True,
    search_hint="gmail email read message view content",
    group="google",
)
def gmail_read(message_id: str) -> dict:
    _check_google()
    from core.auth.gmail_client import GmailClient

    return GmailClient().get_message(message_id)


@oikos_tool(
    name="oikos_google_gmail_send",
    description="Send an email via Gmail (requires approval)",
    privacy=PrivacyTier.SENSITIVE,
    autonomy=AutonomyLevel.ASK_FIRST,
    toolset="google",
    search_hint="gmail email send compose write message",
    group="google",
)
def gmail_send(to: str, subject: str, body: str, html: str | None = None) -> dict:
    _check_google()
    from core.auth.gmail_client import GmailClient

    return GmailClient().send_message(to=to, subject=subject, body=body, html=html)


# ── Calendar ─────────────────────────────────────────────────────────

@oikos_tool(
    name="oikos_google_calendar_list",
    description="List events from a Google Calendar",
    privacy=PrivacyTier.SENSITIVE,
    autonomy=AutonomyLevel.SAFE,
    toolset="google",
    concurrent_safe=True,
    read_only=True,
    search_hint="calendar events schedule list upcoming meetings",
    group="google",
)
def calendar_list(
    calendar_id: str = "primary",
    time_min: str | None = None,
    time_max: str | None = None,
    max_results: int = 10,
    page_token: str | None = None,
) -> dict:
    _check_google()
    from core.auth.calendar_client import CalendarClient

    return CalendarClient().list_events(
        calendar_id=calendar_id, time_min=time_min, time_max=time_max,
        max_results=max_results, page_token=page_token,
    )


@oikos_tool(
    name="oikos_google_calendar_create",
    description="Create a Google Calendar event (requires approval)",
    privacy=PrivacyTier.SENSITIVE,
    autonomy=AutonomyLevel.ASK_FIRST,
    toolset="google",
    search_hint="calendar event create schedule meeting appointment",
    group="google",
)
def calendar_create(
    summary: str,
    start: str,
    end: str,
    calendar_id: str = "primary",
    description: str = "",
    location: str = "",
) -> dict:
    _check_google()
    from core.auth.calendar_client import CalendarClient

    return CalendarClient().create_event(
        calendar_id=calendar_id, summary=summary, start=start, end=end,
        description=description, location=location,
    )


# ── Drive ────────────────────────────────────────────────────────────

@oikos_tool(
    name="oikos_google_drive_list",
    description="List or search Google Drive files",
    privacy=PrivacyTier.SENSITIVE,
    autonomy=AutonomyLevel.SAFE,
    toolset="google",
    concurrent_safe=True,
    read_only=True,
    search_hint="drive files list search documents folders",
    group="google",
)
def drive_list(query: str | None = None, max_results: int = 10, page_token: str | None = None) -> dict:
    _check_google()
    from core.auth.drive_client import DriveClient

    return DriveClient().list_files(query=query, max_results=max_results, page_token=page_token)


@oikos_tool(
    name="oikos_google_drive_read",
    description="Get metadata for a Google Drive file",
    privacy=PrivacyTier.SENSITIVE,
    autonomy=AutonomyLevel.SAFE,
    toolset="google",
    concurrent_safe=True,
    read_only=True,
    search_hint="drive file metadata info details properties",
    group="google",
)
def drive_read(file_id: str) -> dict:
    _check_google()
    from core.auth.drive_client import DriveClient

    return DriveClient().get_file_metadata(file_id)


@oikos_tool(
    name="oikos_google_drive_download",
    description="Download a Google Drive file to staging/ (requires approval)",
    privacy=PrivacyTier.SENSITIVE,
    autonomy=AutonomyLevel.ASK_FIRST,
    toolset="google",
    search_hint="drive download file save export fetch",
    group="google",
)
def drive_download(file_id: str) -> dict:
    _check_google()
    from core.auth.drive_client import DriveClient

    return DriveClient().download_file(file_id)
