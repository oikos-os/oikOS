"""Tests for community theme variants."""

from rich.theme import Theme


class TestThemeVariants:
    def test_all_variants_produce_valid_themes(self):
        from core.interface.theme import THEME_VARIANTS, build_theme

        for name in ("amber", "green", "white"):
            assert name in THEME_VARIANTS
            theme = build_theme(name)
            assert isinstance(theme, Theme)

    def test_all_variants_have_required_tokens(self):
        from core.interface.theme import build_theme

        required = [
            "oikos.primary", "oikos.bright", "oikos.dim", "oikos.faint",
            "oikos.header", "oikos.border", "oikos.success", "oikos.warning",
            "oikos.error", "oikos.system", "oikos.input",
        ]
        for name in ("amber", "green", "white"):
            theme = build_theme(name)
            for token in required:
                assert token in theme.styles, f"{name} missing {token}"

    def test_default_theme_is_amber(self):
        from core.interface.theme import get_active_theme_name

        name = get_active_theme_name()
        assert name == "amber"

    def test_serve_theme_flag_calls_apply_theme(self):
        from unittest.mock import patch

        from click.testing import CliRunner

        from core.interface.cli import main

        with patch("core.interface.theme.apply_theme") as mock_apply, \
             patch("core.interface.api.server.run_server"):
            runner = CliRunner()
            runner.invoke(main, ["serve", "--theme", "green", "--no-boot"])
            mock_apply.assert_called_once_with("green")
