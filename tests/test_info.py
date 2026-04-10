"""Tests for oikos info command."""

import re
from io import StringIO
from unittest.mock import MagicMock, patch

from rich.console import Console

from core.interface.theme import OIKOS_THEME

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


class TestOikosInfo:
    @patch("core.autonomic.fsm.get_current_state")
    @patch("core.safety.credits.load_credits")
    @patch("core.cognition.inference.check_inference_model", return_value=True)
    @patch("core.rooms.manager.get_room_manager")
    @patch("core.memory.indexer.get_table_stats")
    def test_renders_without_exception(self, mock_stats, mock_mgr, _inf, mock_cred, mock_fsm):
        from core.interface.info import render_info

        mock_stats.return_value = {"total_rows": 500, "unique_files": 80, "tier_breakdown": {}}
        room = MagicMock()
        room.id = "home"
        room.name = "Home"
        mock_mgr.return_value.get_active_room.return_value = room
        mock_mgr.return_value.list_rooms.return_value = [room]
        cred = MagicMock()
        cred.used = 100
        cred.monthly_cap = 5000
        mock_cred.return_value = cred
        state = MagicMock()
        state.value = "active"
        mock_fsm.return_value = state

        buf = StringIO()
        c = Console(file=buf, force_terminal=True, theme=OIKOS_THEME)
        render_info(c)
        output = _ANSI_RE.sub("", buf.getvalue())
        assert "oikOS" in output
        assert "80 files" in output
        assert "NEVER_LEAVE" in output

    @patch("core.autonomic.fsm.get_current_state")
    @patch("core.safety.credits.load_credits")
    @patch("core.cognition.inference.check_inference_model", return_value=True)
    @patch("core.rooms.manager.get_room_manager")
    @patch("core.memory.indexer.get_table_stats")
    def test_color_bars_rendered(self, mock_stats, mock_mgr, _inf, mock_cred, mock_fsm):
        from core.interface.info import render_info

        mock_stats.return_value = {"total_rows": 500, "unique_files": 80, "tier_breakdown": {}}
        room = MagicMock()
        room.id = "home"
        room.name = "Home"
        mock_mgr.return_value.get_active_room.return_value = room
        mock_mgr.return_value.list_rooms.return_value = [room]
        cred = MagicMock()
        cred.used = 100
        cred.monthly_cap = 5000
        mock_cred.return_value = cred
        state = MagicMock()
        state.value = "active"
        mock_fsm.return_value = state

        buf = StringIO()
        c = Console(file=buf, force_terminal=True, theme=OIKOS_THEME)
        render_info(c)
        output = _ANSI_RE.sub("", buf.getvalue())
        assert "\u2588" in output

    @patch("core.autonomic.fsm.get_current_state")
    @patch("core.safety.credits.load_credits")
    @patch("core.cognition.inference.check_inference_model", return_value=True)
    @patch("core.rooms.manager.get_room_manager")
    @patch("core.memory.indexer.get_table_stats")
    def test_room_list_shows_active(self, mock_stats, mock_mgr, _inf, mock_cred, mock_fsm):
        from core.interface.info import render_info

        mock_stats.return_value = {"total_rows": 500, "unique_files": 80, "tier_breakdown": {}}
        home = MagicMock()
        home.id = "home"
        home.name = "Home"
        researcher = MagicMock()
        researcher.id = "researcher"
        researcher.name = "Researcher"
        mock_mgr.return_value.get_active_room.return_value = home
        mock_mgr.return_value.list_rooms.return_value = [home, researcher]
        cred = MagicMock()
        cred.used = 100
        cred.monthly_cap = 5000
        mock_cred.return_value = cred
        state = MagicMock()
        state.value = "active"
        mock_fsm.return_value = state

        buf = StringIO()
        c = Console(file=buf, force_terminal=True, theme=OIKOS_THEME)
        render_info(c)
        output = _ANSI_RE.sub("", buf.getvalue())
        assert "(active)" in output
        assert "Researcher" in output

    @patch("core.interface.config.DAEMON_PID_FILE")
    @patch("core.autonomic.fsm.get_current_state")
    @patch("core.safety.credits.load_credits")
    @patch("core.cognition.inference.check_inference_model", return_value=True)
    @patch("core.rooms.manager.get_room_manager")
    @patch("core.memory.indexer.get_table_stats")
    def test_tagline_below_bars_and_version_dynamic(self, mock_stats, mock_mgr, _inf, mock_cred, mock_fsm, mock_pid_file):
        from core.interface.info import render_info

        mock_stats.return_value = {"total_rows": 500, "unique_files": 80, "tier_breakdown": {}}
        room = MagicMock()
        room.id = "home"
        room.name = "Home"
        mock_mgr.return_value.get_active_room.return_value = room
        mock_mgr.return_value.list_rooms.return_value = [room]
        cred = MagicMock()
        cred.used = 100
        cred.monthly_cap = 5000
        mock_cred.return_value = cred
        state = MagicMock()
        state.value = "active"
        mock_fsm.return_value = state

        buf = StringIO()
        c = Console(file=buf, force_terminal=True, theme=OIKOS_THEME)
        render_info(c)
        output = _ANSI_RE.sub("", buf.getvalue())
        assert "The home for AI agents." in output
        assert output.count("The home for AI agents.") == 1
        from core import __version__
        assert __version__ in output
