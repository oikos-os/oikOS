"""Tests for thinking indicators module."""

from core.interface.thinking import THINKING_INDICATORS, get_thinking_indicator


class TestThinkingIndicators:
    def test_list_not_empty(self):
        assert len(THINKING_INDICATORS) > 0

    def test_all_start_with_diamond(self):
        for ind in THINKING_INDICATORS:
            assert ind.startswith("\u25c8"), f"Indicator missing diamond prefix: {ind}"

    def test_get_returns_from_list(self):
        for _ in range(20):
            result = get_thinking_indicator()
            assert result in THINKING_INDICATORS
