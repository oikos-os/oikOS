"""Tests for the oikOS logo renderer."""
from core.interface.tui.logo import render_house_mark, render_wordmark, render_logo_text


def test_house_mark_has_7_lines():
    lines = render_house_mark()
    assert len(lines) == 7


def test_house_mark_uses_block_chars():
    lines = render_house_mark()
    # Row 3 (widest) should be all filled
    assert "\u2588" in lines[3]  # █ character


def test_wordmark_has_6_lines():
    lines = render_wordmark()
    assert len(lines) == 6


def test_wordmark_contains_box_drawing():
    lines = render_wordmark()
    # pyfiglet ansi_shadow uses ╗ ╔ ║ characters
    joined = "".join(str(line) for line in lines)
    assert "\u2557" in joined or "\u2551" in joined or "\u2588" in joined


def test_logo_text_returns_rich_text():
    from rich.text import Text
    result = render_logo_text()
    assert isinstance(result, Text)


def test_logo_text_contains_house_and_wordmark():
    text = render_logo_text()
    plain = text.plain
    assert "\u2588" in plain  # house blocks
    assert "\u2557" in plain or "\u2551" in plain or "\u2550" in plain  # wordmark box-drawing
