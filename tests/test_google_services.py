"""Tests for Google service clients — base, Gmail, Calendar, Drive."""
from __future__ import annotations

from unittest.mock import MagicMock, patch, PropertyMock

import pytest

from core.auth.google_services import GoogleAPIError, GoogleServiceBase

# Patch target: late imports inside methods resolve from the source module
_TOKENS_PATCH = "core.auth.google_oauth.get_google_tokens"
_REFRESH_PATCH = "core.auth.google_oauth.refresh_google_token"


# ── Fixtures ─────────────────────────────────────────────────────────

def _mock_tokens(access_token: str = "test-token"):
    """Create a mock GoogleTokens."""
    mock = MagicMock()
    mock.access_token = access_token
    return mock


@pytest.fixture()
def mock_google_connected():
    """Patch google_oauth to return connected state with valid token."""
    with patch(_TOKENS_PATCH, return_value=_mock_tokens()):
        yield


# ── GoogleServiceBase ────────────────────────────────────────────────

class TestGoogleServiceBase:
    def test_raises_when_not_connected(self):
        with patch(_TOKENS_PATCH, return_value=None):
            base = GoogleServiceBase()
            with pytest.raises(GoogleAPIError, match="Google not connected"):
                base._get_token()

    def test_get_token_returns_access_token(self, mock_google_connected):
        base = GoogleServiceBase()
        assert base._get_token() == "test-token"

    @patch(_TOKENS_PATCH, return_value=_mock_tokens())
    def test_request_adds_auth_header(self, mock_tokens):
        base = GoogleServiceBase()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        base._client = MagicMock()
        base._client.request.return_value = mock_resp

        base._request("GET", "https://example.com/api")

        call_kwargs = base._client.request.call_args
        assert "Authorization" in call_kwargs.kwargs.get("headers", call_kwargs[1].get("headers", {}))

    @patch(_TOKENS_PATCH, return_value=_mock_tokens())
    @patch(_REFRESH_PATCH, return_value=True)
    def test_auto_refresh_on_401(self, mock_refresh, mock_tokens):
        base = GoogleServiceBase()
        first_resp = MagicMock()
        first_resp.status_code = 401
        second_resp = MagicMock()
        second_resp.status_code = 200
        base._client = MagicMock()
        base._client.request.side_effect = [first_resp, second_resp]

        result = base._request("GET", "https://example.com/api")

        mock_refresh.assert_called_once()
        assert base._client.request.call_count == 2

    @patch(_TOKENS_PATCH, return_value=_mock_tokens())
    def test_raises_google_api_error_on_4xx(self, mock_tokens):
        base = GoogleServiceBase()
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        mock_resp.json.return_value = {"error": {"message": "Not Found"}}
        base._client = MagicMock()
        base._client.request.return_value = mock_resp

        with pytest.raises(GoogleAPIError) as exc:
            base._request("GET", "https://example.com/api")
        assert exc.value.status_code == 404

    @patch(_TOKENS_PATCH, return_value=_mock_tokens())
    def test_error_message_redacted_on_parse_failure(self, mock_tokens):
        base = GoogleServiceBase()
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.json.side_effect = ValueError("bad json")
        mock_resp.text = "Internal Server Error details"
        base._client = MagicMock()
        base._client.request.return_value = mock_resp

        with pytest.raises(GoogleAPIError) as exc:
            base._request("GET", "https://example.com/api")
        assert exc.value.status_code == 500


# ── GmailClient ──────────────────────────────────────────────────────

class TestGmailClient:
    @patch(_TOKENS_PATCH, return_value=_mock_tokens())
    def test_list_messages(self, mock_tokens):
        from core.auth.gmail_client import GmailClient

        client = GmailClient()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "messages": [{"id": "msg1"}, {"id": "msg2"}],
            "nextPageToken": "token2",
            "resultSizeEstimate": 50,
        }
        client._client = MagicMock()
        client._client.request.return_value = mock_resp

        result = client.list_messages(query="from:test@example.com", max_results=5)
        assert len(result["messages"]) == 2
        assert result["next_page_token"] == "token2"

    @patch(_TOKENS_PATCH, return_value=_mock_tokens())
    def test_get_message_parses_body(self, mock_tokens):
        from core.auth.gmail_client import GmailClient
        import base64

        body_text = "Hello, this is the email body."
        encoded = base64.urlsafe_b64encode(body_text.encode()).decode()

        client = GmailClient()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "id": "msg1",
            "threadId": "thread1",
            "snippet": "Hello",
            "labelIds": ["INBOX"],
            "payload": {
                "headers": [
                    {"name": "Subject", "value": "Test Subject"},
                    {"name": "From", "value": "sender@example.com"},
                    {"name": "To", "value": "me@example.com"},
                    {"name": "Date", "value": "Mon, 23 Mar 2026"},
                ],
                "mimeType": "text/plain",
                "body": {"data": encoded},
            },
        }
        client._client = MagicMock()
        client._client.request.return_value = mock_resp

        result = client.get_message("msg1")
        assert result["subject"] == "Test Subject"
        assert result["from"] == "sender@example.com"
        assert "Hello" in result["body"]

    @patch(_TOKENS_PATCH, return_value=_mock_tokens())
    def test_send_message(self, mock_tokens):
        from core.auth.gmail_client import GmailClient

        client = GmailClient()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"id": "sent1", "threadId": "thread1"}
        client._client = MagicMock()
        client._client.request.return_value = mock_resp

        result = client.send_message("to@example.com", "Subject", "Body text")
        assert result["id"] == "sent1"
        # Verify raw base64 payload was sent
        call_kwargs = client._client.request.call_args
        assert call_kwargs.kwargs.get("json", {}).get("raw") is not None

    @patch(_TOKENS_PATCH, return_value=_mock_tokens())
    def test_list_labels(self, mock_tokens):
        from core.auth.gmail_client import GmailClient

        client = GmailClient()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "labels": [{"id": "INBOX", "name": "INBOX"}, {"id": "SENT", "name": "SENT"}],
        }
        client._client = MagicMock()
        client._client.request.return_value = mock_resp

        result = client.list_labels()
        assert len(result) == 2

    @patch(_TOKENS_PATCH, return_value=_mock_tokens())
    def test_list_messages_with_pagination(self, mock_tokens):
        from core.auth.gmail_client import GmailClient

        client = GmailClient()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"messages": [{"id": "msg3"}], "nextPageToken": None}
        client._client = MagicMock()
        client._client.request.return_value = mock_resp

        result = client.list_messages(page_token="token2")
        # Verify page_token was passed
        call_kwargs = client._client.request.call_args
        assert "pageToken" in (call_kwargs.kwargs.get("params") or {})


# ── CalendarClient ───────────────────────────────────────────────────

class TestCalendarClient:
    @patch(_TOKENS_PATCH, return_value=_mock_tokens())
    def test_list_calendars(self, mock_tokens):
        from core.auth.calendar_client import CalendarClient

        client = CalendarClient()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "items": [{"id": "primary", "summary": "My Calendar"}],
        }
        client._client = MagicMock()
        client._client.request.return_value = mock_resp

        result = client.list_calendars()
        assert len(result) == 1
        assert result[0]["summary"] == "My Calendar"

    @patch(_TOKENS_PATCH, return_value=_mock_tokens())
    def test_list_events(self, mock_tokens):
        from core.auth.calendar_client import CalendarClient

        client = CalendarClient()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "items": [
                {"id": "evt1", "summary": "Meeting", "start": {"dateTime": "2026-03-25T10:00:00"}},
            ],
            "nextPageToken": None,
        }
        client._client = MagicMock()
        client._client.request.return_value = mock_resp

        result = client.list_events(time_min="2026-03-25T00:00:00Z")
        assert len(result["events"]) == 1
        assert result["events"][0]["summary"] == "Meeting"

    @patch(_TOKENS_PATCH, return_value=_mock_tokens())
    def test_create_event(self, mock_tokens):
        from core.auth.calendar_client import CalendarClient

        client = CalendarClient()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"id": "new_evt", "summary": "New Meeting"}
        client._client = MagicMock()
        client._client.request.return_value = mock_resp

        result = client.create_event(
            summary="New Meeting",
            start="2026-03-25T10:00:00-04:00",
            end="2026-03-25T11:00:00-04:00",
        )
        assert result["summary"] == "New Meeting"

    @patch(_TOKENS_PATCH, return_value=_mock_tokens())
    def test_get_event(self, mock_tokens):
        from core.auth.calendar_client import CalendarClient

        client = CalendarClient()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"id": "evt1", "summary": "Standup"}
        client._client = MagicMock()
        client._client.request.return_value = mock_resp

        result = client.get_event("primary", "evt1")
        assert result["id"] == "evt1"


# ── DriveClient ──────────────────────────────────────────────────────

class TestDriveClient:
    @patch(_TOKENS_PATCH, return_value=_mock_tokens())
    def test_list_files(self, mock_tokens):
        from core.auth.drive_client import DriveClient

        client = DriveClient()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "files": [{"id": "f1", "name": "doc.txt", "mimeType": "text/plain"}],
            "nextPageToken": None,
        }
        client._client = MagicMock()
        client._client.request.return_value = mock_resp

        result = client.list_files(max_results=5)
        assert len(result["files"]) == 1

    @patch(_TOKENS_PATCH, return_value=_mock_tokens())
    def test_search_files(self, mock_tokens):
        from core.auth.drive_client import DriveClient

        client = DriveClient()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"files": [], "nextPageToken": None}
        client._client = MagicMock()
        client._client.request.return_value = mock_resp

        result = client.search_files("report")
        # Verify search query format
        call_kwargs = client._client.request.call_args
        params = call_kwargs.kwargs.get("params") or {}
        assert "name contains" in params.get("q", "")

    @patch(_TOKENS_PATCH, return_value=_mock_tokens())
    def test_get_file_metadata(self, mock_tokens):
        from core.auth.drive_client import DriveClient

        client = DriveClient()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "id": "f1", "name": "doc.txt", "mimeType": "text/plain", "size": "1024",
        }
        client._client = MagicMock()
        client._client.request.return_value = mock_resp

        result = client.get_file_metadata("f1")
        assert result["name"] == "doc.txt"

    @patch(_TOKENS_PATCH, return_value=_mock_tokens())
    def test_download_file(self, mock_tokens, tmp_path):
        from core.auth.drive_client import DriveClient

        client = DriveClient()
        # Mock: first call = metadata, second call = download
        meta_resp = MagicMock()
        meta_resp.status_code = 200
        meta_resp.json.return_value = {"id": "f1", "name": "test.txt", "mimeType": "text/plain"}

        download_resp = MagicMock()
        download_resp.status_code = 200
        download_resp.content = b"file contents here"

        client._client = MagicMock()
        client._client.request.side_effect = [meta_resp, download_resp]

        dest = tmp_path / "test.txt"
        result = client.download_file("f1", destination=str(dest))
        assert result["name"] == "test.txt"
        assert result["size_bytes"] == 18
        assert dest.read_bytes() == b"file contents here"

    @patch(_TOKENS_PATCH, return_value=_mock_tokens())
    def test_search_escapes_quotes(self, mock_tokens):
        from core.auth.drive_client import DriveClient

        client = DriveClient()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"files": [], "nextPageToken": None}
        client._client = MagicMock()
        client._client.request.return_value = mock_resp

        client.search_files("it's a test")
        call_kwargs = client._client.request.call_args
        params = call_kwargs.kwargs.get("params") or {}
        assert "\\'" in params.get("q", "")
