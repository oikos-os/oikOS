"""Tests for Phase C CLI enhancements."""

import re
from io import StringIO
from unittest.mock import patch

from rich.console import Console

from core.interface.theme import build_theme

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


class TestBrandedErrors:
    def test_no_backend_error_renders(self):
        from core.interface.errors import show_error

        buf = StringIO()
        c = Console(file=buf, force_terminal=True, theme=build_theme("amber"))
        show_error("no_backend", console=c)
        output = _ANSI_RE.sub("", buf.getvalue())
        assert "No inference backend detected" in output
        assert "Install" in output

    def test_vault_empty_error_renders(self):
        from core.interface.errors import show_error

        buf = StringIO()
        c = Console(file=buf, force_terminal=True, theme=build_theme("amber"))
        show_error("vault_empty", console=c)
        output = _ANSI_RE.sub("", buf.getvalue())
        assert "vault is empty" in output
        assert "vault/knowledge/" in output


class TestBrandedHelp:
    def test_root_command_shows_snapshot(self):
        """Bare `oikos` now renders a system snapshot, not branded help."""
        from unittest.mock import patch as _patch
        from click.testing import CliRunner

        from core.interface.cli import main

        runner = CliRunner()
        with _patch("core.interface.snapshot.httpx.get", side_effect=Exception("offline")):
            result = runner.invoke(main, [])

        output = _ANSI_RE.sub("", result.output)
        assert "oikOS" in output
        assert "room" in output
        assert "provider" in output
