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
        room.name = "home"
        mock_mgr.return_value.get_active_room.return_value = room
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
