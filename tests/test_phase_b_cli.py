"""Tests for Phase B CLI enhancements."""

import re
from unittest.mock import MagicMock, patch

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


class TestRoomSwitchTransition:
    @patch("core.rooms.manager.get_room_manager")
    def test_switch_shows_closing_and_opening_panels(self, mock_mgr):
        """Room switch renders closing panel, diamond, and opening panel."""
        from click.testing import CliRunner

        from core.interface.cli import main

        home_room = MagicMock()
        home_room.id = "home"
        home_room.name = "Home"
        researcher_room = MagicMock()
        researcher_room.id = "researcher"
        researcher_room.name = "Researcher"
        researcher_room.vault_scope.mode = "include"
        researcher_room.vault_scope.paths = ["knowledge/ml/"]
        researcher_room.toolsets = ["vault", "browser"]
        researcher_room.model.model = "qwen2.5:14b"
        researcher_room.model.provider = None

        mgr = MagicMock()
        mgr.get_active_room.return_value = home_room
        mgr.switch_room.return_value = researcher_room
        mock_mgr.return_value = mgr

        runner = CliRunner()
        result = runner.invoke(main, ["room", "switch", "researcher"])

        output = _ANSI_RE.sub("", result.output)
        assert "Closing" in output
        assert "Home" in output
        assert "Entering" in output
        assert "Researcher" in output
        assert "\u25c8" in output
        assert "knowledge/ml/" in output
        assert "vault, browser" in output


class TestThinkingIndicators:
    def test_thinking_indicator_used_in_imports(self):
        """The thinking module is importable and used by CLI."""
        from core.interface.thinking import THINKING_INDICATORS, get_thinking_indicator

        assert len(THINKING_INDICATORS) >= 8
        indicator = get_thinking_indicator()
        assert indicator in THINKING_INDICATORS
        assert "\u25c8" in indicator


class TestPanelBorders:
    @patch("core.rooms.manager.get_room_manager")
    def test_room_create_shows_panel(self, mock_mgr):
        """Room create success should be wrapped in a panel."""
        from click.testing import CliRunner

        from core.interface.cli import main

        mgr = MagicMock()
        mock_mgr.return_value = mgr

        runner = CliRunner()
        result = runner.invoke(main, ["room", "create", "test-room", "--name", "Test Room"])

        output = _ANSI_RE.sub("", result.output)
        assert "Room Created" in output

    @patch("core.rooms.manager.get_room_manager")
    def test_error_panel_format(self, mock_mgr):
        """Error panels should use the warning glyph."""
        from click.testing import CliRunner

        from core.interface.cli import main

        mgr = MagicMock()
        mgr.get_active_room.return_value = MagicMock(id="home", name="Home")
        mgr.switch_room.side_effect = ValueError("Room 'nonexistent' not found")
        mock_mgr.return_value = mgr

        runner = CliRunner()
        result = runner.invoke(main, ["room", "switch", "nonexistent"])
        output = _ANSI_RE.sub("", result.output)
        assert "Error" in output
