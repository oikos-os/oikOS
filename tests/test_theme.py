"""Tests for oikOS Rich theme system."""

from io import StringIO

from rich.console import Console

from core.interface.theme import OIKOS_THEME, console, render_banner


class TestOikosTheme:
    def test_all_tokens_resolve(self):
        expected = [
            "oikos.primary",
            "oikos.bright",
            "oikos.dim",
            "oikos.faint",
            "oikos.header",
            "oikos.border",
            "oikos.success",
            "oikos.warning",
            "oikos.error",
            "oikos.system",
            "oikos.input",
        ]
        for token in expected:
            assert token in OIKOS_THEME.styles, f"Missing theme token: {token}"

    def test_console_uses_theme(self):
        style = console.get_style("oikos.primary")
        assert style.color is not None

    def test_banner_renders_and_contains_oikos(self):
        buf = StringIO()
        test_console = Console(file=buf, force_terminal=True, theme=OIKOS_THEME)
        render_banner(test_console)
        output = buf.getvalue()
        # pyfiglet "slant" renders as ASCII art — check output is non-trivial
        assert len(output.strip()) > 50
        # Verify the amber gradient escape codes are present
        assert "\x1b[" in output
