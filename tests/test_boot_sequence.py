"""Tests for oikOS phosphor boot sequence."""

import re
from io import StringIO
from unittest.mock import MagicMock, patch

from rich.console import Console

from core.interface.theme import OIKOS_THEME

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


class TestBootSequence:
    def _make_console(self):
        buf = StringIO()
        return Console(file=buf, force_terminal=True, theme=OIKOS_THEME), buf

    @patch("core.interface.boot.time")
    @patch("core.interface.boot.random")
    @patch("core.rooms.manager.get_room_manager")
    @patch("core.memory.indexer.get_table_stats")
    def test_boot_sequence_completes(self, mock_stats, mock_mgr, mock_random, mock_time):
        mock_stats.return_value = {"total_rows": 500, "unique_files": 80, "tier_breakdown": {}}
        room = MagicMock()
        room.name = "home"
        mock_mgr.return_value.get_active_room.return_value = room
        mock_random.uniform.return_value = 0
        mock_random.randint.return_value = 2
        mock_time.sleep = MagicMock()

        from core.interface.boot import run_boot_sequence

        c, buf = self._make_console()
        run_boot_sequence(c, port=8420, dev=False)
        output = _ANSI_RE.sub("", buf.getvalue())
        assert "BIOS" in output
        assert "80 files" in output

    @patch("core.interface.api.server.run_server")
    @patch("core.interface.boot.run_boot_sequence")
    @patch("core.onboarding.state.is_onboarding_complete", return_value=True)
    def test_no_boot_flag_skips_sequence(self, _onboard, mock_boot, _server):
        from click.testing import CliRunner

        from core.interface.cli import main

        runner = CliRunner()
        runner.invoke(main, ["serve", "--no-boot"])
        mock_boot.assert_not_called()
