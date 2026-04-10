"""Tests for the TUI Chat view."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Input, Select, Static

from core.interface.tui.views.chat import ChatView


class ChatTestApp(App):
    """Minimal app wrapping ChatView for isolated testing."""

    CSS = """
    Screen { background: #0D0D0D; }
    #chat-layout { height: 1fr; }
    #message-list { height: 1fr; }
    #chat-input { height: 1; }
    #tool-panel { display: none; }
    #tool-panel.visible { display: block; }
    """

    def __init__(self) -> None:
        super().__init__()
        self.api_client = AsyncMock()

    def compose(self) -> ComposeResult:
        yield ChatView(id="chat")


@pytest.fixture
def chat_app():
    return ChatTestApp()


@pytest.mark.asyncio
async def test_chat_composes(chat_app):
    async with chat_app.run_test(size=(120, 40)) as pilot:
        chat = chat_app.query_one(ChatView)
        assert chat is not None


@pytest.mark.asyncio
async def test_chat_has_message_list(chat_app):
    async with chat_app.run_test(size=(120, 40)) as pilot:
        msg_list = chat_app.query_one("#message-list")
        assert msg_list is not None


@pytest.mark.asyncio
async def test_chat_has_input(chat_app):
    async with chat_app.run_test(size=(120, 40)) as pilot:
        input_area = chat_app.query_one("#chat-input")
        assert input_area is not None
        assert isinstance(input_area, Input)


@pytest.mark.asyncio
async def test_chat_has_model_select(chat_app):
    async with chat_app.run_test(size=(120, 40)) as pilot:
        select = chat_app.query_one("#model-select")
        assert select is not None
        assert isinstance(select, Select)


@pytest.mark.asyncio
async def test_chat_has_header(chat_app):
    async with chat_app.run_test(size=(120, 40)) as pilot:
        header = chat_app.query_one("#chat-header")
        assert header is not None


@pytest.mark.asyncio
async def test_chat_add_user_message(chat_app):
    async with chat_app.run_test(size=(120, 40)) as pilot:
        chat = chat_app.query_one(ChatView)
        chat.add_message("user", "Hello world")
        await pilot.pause()
        messages = chat_app.query(".chat-message-user")
        assert len(messages) >= 1


@pytest.mark.asyncio
async def test_chat_add_assistant_message(chat_app):
    async with chat_app.run_test(size=(120, 40)) as pilot:
        chat = chat_app.query_one(ChatView)
        chat.add_message("assistant", "Hi there", model="qwen2.5:14b")
        await pilot.pause()
        messages = chat_app.query(".chat-message-agent")
        assert len(messages) >= 1


@pytest.mark.asyncio
async def test_chat_clear(chat_app):
    async with chat_app.run_test(size=(120, 40)) as pilot:
        chat = chat_app.query_one(ChatView)
        chat.add_message("user", "Test message")
        await pilot.pause()
        assert len(chat_app.query(".chat-message-user")) >= 1
        # Focus the chat and clear
        chat.focus()
        await pilot.press("ctrl+l")
        await pilot.pause()
        messages = chat_app.query(".chat-message-user")
        assert len(messages) == 0


@pytest.mark.asyncio
async def test_chat_update_models(chat_app):
    async with chat_app.run_test(size=(120, 40)) as pilot:
        chat = chat_app.query_one(ChatView)
        chat.update_models({
            "local": [{"id": "qwen2.5:14b", "name": "qwen2.5:14b"}],
            "cloud": [{"id": "gemini-2.5-pro", "name": "gemini-2.5-pro", "provider": "gemini"}],
        })
        await pilot.pause()
        select = chat_app.query_one("#model-select", Select)
        # Should have Auto + 2 models = 3 options
        assert select._options is not None


@pytest.mark.asyncio
async def test_chat_update_room(chat_app):
    async with chat_app.run_test(size=(120, 40)) as pilot:
        chat = chat_app.query_one(ChatView)
        chat.update_room("Research")
        await pilot.pause()
        header = chat_app.query_one("#chat-header", Static)
        text = str(header.render())
        assert "Research" in text


@pytest.mark.asyncio
async def test_chat_tool_panel_hidden_by_default(chat_app):
    async with chat_app.run_test(size=(120, 40)) as pilot:
        panel = chat_app.query_one("#tool-panel")
        assert "visible" not in panel.classes


@pytest.mark.asyncio
async def test_chat_tool_panel_toggle(chat_app):
    async with chat_app.run_test(size=(120, 40)) as pilot:
        chat = chat_app.query_one(ChatView)
        chat.focus()
        await pilot.press("f8")
        await pilot.pause()
        panel = chat_app.query_one("#tool-panel")
        assert "visible" in panel.classes
        await pilot.press("f8")
        await pilot.pause()
        assert "visible" not in panel.classes


@pytest.mark.asyncio
async def test_chat_user_message_prefix(chat_app):
    """User messages use thin arrow prefix, not 'You:'."""
    async with chat_app.run_test(size=(120, 40)) as pilot:
        chat = chat_app.query_one(ChatView)
        widget = chat.add_message("user", "hello")
        rendered = str(widget.render())
        assert "\u25b8" in rendered
        assert "You:" not in rendered


@pytest.mark.asyncio
async def test_chat_agent_message_prefix(chat_app):
    """Agent messages use diamond prefix with model badge at end."""
    async with chat_app.run_test(size=(120, 40)) as pilot:
        chat = chat_app.query_one(ChatView)
        widget = chat.add_message("assistant", "hi", model="qwen2.5:14b")
        rendered = str(widget.render())
        assert "\u25c8" in rendered
        assert "oikOS" not in rendered
