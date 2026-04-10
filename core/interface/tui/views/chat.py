"""Chat view — primary interaction screen for oikOS TUI."""
from __future__ import annotations

import logging

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, VerticalScroll
from textual.widget import Widget
from textual.widgets import Input, Select, Static

from core.interface.thinking import get_thinking_indicator

log = logging.getLogger(__name__)

# Markdown → Rich markup (lightweight, no full parser)
_MD_BOLD = __import__("re").compile(r"\*\*(.+?)\*\*")
_MD_ITALIC = __import__("re").compile(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)")
_MD_CODE = __import__("re").compile(r"`([^`]+)`")


def _md_to_rich(text: str) -> str:
    """Convert basic markdown bold/italic/code to Rich markup."""
    text = _MD_BOLD.sub(r"[bold]\1[/bold]", text)
    text = _MD_ITALIC.sub(r"[italic]\1[/italic]", text)
    text = _MD_CODE.sub(r"[reverse]\1[/reverse]", text)
    return text


class ChatView(Widget, can_focus=True):
    """Chat screen: message list, model dropdown, streaming responses."""

    BINDINGS = [
        Binding("ctrl+l", "clear_chat", "Clear", show=True),
        Binding("f8", "toggle_tools", "Tools", show=True),
    ]

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._selected_model: str | None = None
        self._response_text: str = ""
        self._streaming: bool = False
        self._room_name: str = "Home"

    def compose(self) -> ComposeResult:
        with Vertical(id="chat-layout"):
            yield Static(
                "Home \u00b7 Auto",
                id="chat-header",
            )
            yield Select(
                [("Auto", "auto")],
                value="auto",
                id="model-select",
                allow_blank=False,
            )
            yield VerticalScroll(id="message-list")
            yield Vertical(id="tool-panel")
            yield Input(placeholder="Send a message...", id="chat-input")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle Enter on the chat input."""
        if event.input.id == "chat-input" and not self._streaming:
            self._send_message()

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id == "model-select":
            val = event.value
            self._selected_model = None if val == "auto" else str(val)
            model_label = "Auto" if val == "auto" else str(val)
            room = self._get_room_name()
            self.query_one("#chat-header", Static).update(
                f"{room} \u00b7 {model_label}"
            )

    # --- Public API ----------------------------------------------------------

    def add_message(self, role: str, text: str, model: str | None = None, badge: str = "") -> Static:
        """Add a message to the message list and return the widget."""
        msg_list = self.query_one("#message-list", VerticalScroll)
        if role == "user":
            widget = Static(f"\u25b8 {text}", classes="chat-message-user")
        else:
            model_tag = f" [#6B5012]\\[{model}][/]" if model else ""
            badge_line = f"\n[#6B5012]{badge}[/]" if badge else ""
            widget = Static(f"\u25c8 {_md_to_rich(text)}{model_tag}{badge_line}", classes="chat-message-agent")
        msg_list.mount(widget)
        msg_list.scroll_end(animate=False)
        return widget

    def update_models(self, models: dict) -> None:
        """Populate the model Select widget from /api/models response."""
        options: list[tuple[str, str]] = [("Auto", "auto")]
        for m in models.get("local", []):
            name = m.get("name", m.get("id", "?"))
            options.append((f"{name} (local)", name))
        for m in models.get("cloud", []):
            name = m.get("name", m.get("id", "?"))
            provider = m.get("provider", "cloud")
            options.append((f"{name} ({provider})", name))
        select = self.query_one("#model-select", Select)
        select.set_options(options)

    def update_room(self, room_name: str) -> None:
        """Update the room display in the chat header."""
        self._room_name = room_name
        model_label = "Auto" if self._selected_model is None else self._selected_model
        self.query_one("#chat-header", Static).update(
            f"{room_name} \u00b7 {model_label}"
        )

    # --- Actions -------------------------------------------------------------

    def action_clear_chat(self) -> None:
        """Remove all messages from the message list."""
        msg_list = self.query_one("#message-list", VerticalScroll)
        for child in list(msg_list.children):
            child.remove()

    def action_toggle_tools(self) -> None:
        """Toggle the tool activity panel."""
        panel = self.query_one("#tool-panel")
        panel.toggle_class("visible")

    # --- Internal ------------------------------------------------------------

    def _get_room_name(self) -> str:
        return self._room_name

    def _send_message(self) -> None:
        """Extract text from input, add user message, start streaming."""
        inp = self.query_one("#chat-input", Input)
        text = inp.value.strip()
        if not text:
            return
        inp.value = ""
        self.add_message("user", text)
        # Show thinking indicator
        msg_list = self.query_one("#message-list", VerticalScroll)
        thinking = Static(get_thinking_indicator(), classes="chat-thinking", id="thinking-indicator")
        msg_list.mount(thinking)
        msg_list.scroll_end(animate=False)
        self._response_text = ""
        self._streaming = True
        self.run_worker(self._stream_response(text), exclusive=True)

    async def _stream_response(self, query: str) -> None:
        """Stream response from the API and update the assistant message."""
        client = self.app.api_client
        placeholder = self._add_assistant_placeholder()
        try:
            async for chunk in client.chat_stream(query, model=self._selected_model):
                if "delta" in chunk:
                    self._response_text += chunk["delta"]
                    placeholder.update(self._format_assistant(self._response_text, "..."))
                    self.query_one("#message-list").scroll_end(animate=False)
                elif chunk.get("done"):
                    model = chunk.get("model", "unknown")
                    auto = chunk.get("auto", False)
                    label = f"{model} (auto)" if auto else model
                    badge = ""
                    rt = chunk.get("routing_trace")
                    if rt and rt.get("badge"):
                        badge = rt["badge"]
                    placeholder.update(self._format_assistant(self._response_text, label, badge))
                    # Add tool info if present
                    if chunk.get("tools_used"):
                        self._add_tool_lines(chunk["tools_used"])
        except Exception as exc:
            if not self._response_text:
                placeholder.update(f"\u25c8 [error] {type(exc).__name__}")
        finally:
            self._remove_thinking()
            self._streaming = False

    def _add_assistant_placeholder(self) -> Static:
        """Add an empty assistant message widget and return it."""
        msg_list = self.query_one("#message-list", VerticalScroll)
        widget = Static("\u25c8 ...", classes="chat-message-agent")
        msg_list.mount(widget)
        return widget

    def _format_assistant(self, text: str, model: str, badge: str = "") -> str:
        badge_line = f"\n[#6B5012]{badge}[/]" if badge else ""
        return f"\u25c8 {_md_to_rich(text)} [#6B5012]\\[{model}][/]{badge_line}"

    def _remove_thinking(self) -> None:
        try:
            self.query_one("#thinking-indicator").remove()
        except Exception as e:
            log.debug("thinking indicator removal suppressed: %s", e)

    def _add_tool_lines(self, tools: list) -> None:
        panel = self.query_one("#tool-panel")
        for tool in tools:
            name = tool if isinstance(tool, str) else tool.get("name", str(tool))
            panel.mount(Static(f"  \u25b8 {name}", classes="chat-tool-activity"))
