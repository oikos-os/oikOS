from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from core.agency.compressor import RuleCompressor, LLMCompressor, compress
from core.agency.context_engine import estimate_tokens


# ── RuleCompressor: null stripping ──────────────────────────────────────


class TestRuleCompressorNulls:
    def test_strips_null_and_empty(self):
        raw = json.dumps({"name": "foo", "bar": None, "baz": ""})
        result = json.loads(RuleCompressor.compress(raw))
        assert result == {"name": "foo"}

    def test_strips_nested_nulls(self):
        raw = json.dumps({"a": {"b": None, "c": "keep"}, "d": None})
        result = json.loads(RuleCompressor.compress(raw))
        assert result == {"a": {"c": "keep"}}

    def test_strips_50_nulls_keeps_real(self):
        data = {f"null_{i}": None for i in range(50)}
        data["real"] = "value"
        raw = json.dumps(data)
        result = json.loads(RuleCompressor.compress(raw))
        assert result == {"real": "value"}


# ── RuleCompressor: array truncation ────────────────────────────────────


class TestRuleCompressorArrays:
    def test_truncates_long_array(self):
        data = {"items": list(range(47))}
        raw = json.dumps(data)
        result = json.loads(RuleCompressor.compress(raw))
        assert len(result["items"]) == 4
        assert result["items"][:3] == [0, 1, 2]
        assert "3 of 47" in str(result["items"][3])

    def test_preserves_short_array(self):
        data = {"items": [1, 2, 3]}
        raw = json.dumps(data)
        result = json.loads(RuleCompressor.compress(raw))
        assert result["items"] == [1, 2, 3]

    def test_truncates_top_level_array(self):
        data = list(range(10))
        raw = json.dumps(data)
        result = json.loads(RuleCompressor.compress(raw))
        assert len(result) == 4
        assert result[:3] == [0, 1, 2]
        assert "3 of 10" in str(result[3])


# ── RuleCompressor: number abbreviation ─────────────────────────────────


class TestRuleCompressorNumbers:
    def test_abbreviates_millions(self):
        result = RuleCompressor.compress("Population is 1200000 people")
        assert "1.2M" in result

    def test_abbreviates_thousands(self):
        result = RuleCompressor.compress("Revenue was 45000 dollars")
        assert "45.0K" in result

    def test_preserves_small_numbers(self):
        result = RuleCompressor.compress("There are 42 items")
        assert "42" in result
        assert "K" not in result
        assert "M" not in result


# ── RuleCompressor: HTML / CLIXML / whitespace ──────────────────────────


class TestRuleCompressorMarkup:
    def test_strips_html_tags(self):
        result = RuleCompressor.compress("<p>Hello <b>world</b></p>")
        assert "<p>" not in result
        assert "<b>" not in result
        assert "Hello" in result
        assert "world" in result

    def test_strips_nested_html(self):
        result = RuleCompressor.compress("<div><span><a href='x'>link</a></span></div>")
        assert "<" not in result
        assert "link" in result

    def test_strips_clixml(self):
        clixml = '#< CLIXML\n<Objs Version="1.1"><S>error text</S>\n</Objs>'
        result = RuleCompressor.compress(clixml)
        assert "CLIXML" not in result
        assert "<Objs" not in result

    def test_collapses_multiple_newlines(self):
        result = RuleCompressor.compress("line1\n\n\n\n\nline2")
        assert "\n\n\n" not in result
        assert "line1" in result
        assert "line2" in result


# ── RuleCompressor: large input reduction ───────────────────────────────


class TestRuleCompressorReduction:
    def test_large_input_significantly_reduced(self):
        data = {f"key {i}": None if i % 2 == 0 else f"value number {i}" for i in range(2000)}
        data["big array"] = list(range(200))
        raw = json.dumps(data)
        assert estimate_tokens(raw) > 5000
        result = RuleCompressor.compress(raw)
        assert estimate_tokens(result) < estimate_tokens(raw) * 0.6


# ── LLMCompressor ───────────────────────────────────────────────────────


class TestLLMCompressor:
    @patch("core.agency.compressor.generate_local")
    def test_compresses_via_llm(self, mock_gen):
        mock_gen.return_value = {"response": "Summary of the data."}
        result = LLMCompressor.compress("A very long text about many things.", "find the answer")
        assert result == "Summary of the data."
        mock_gen.assert_called_once()

    @patch("core.agency.compressor.generate_local")
    def test_fallback_on_llm_error(self, mock_gen):
        mock_gen.side_effect = Exception("model offline")
        long_text = " ".join(["word"] * 500)
        result = LLMCompressor.compress(long_text, "task")
        assert len(result) > 0
        assert estimate_tokens(result) <= 256

    @patch("core.agency.compressor.generate_local")
    def test_respects_max_tokens(self, mock_gen):
        verbose = " ".join(["word"] * 500)
        mock_gen.return_value = {"response": verbose}
        result = LLMCompressor.compress("input", "task", max_tokens=50)
        assert estimate_tokens(result) <= 50


# ── Pipeline ────────────────────────────────────────────────────────────


class TestCompressPipeline:
    @patch("core.agency.compressor.generate_local")
    def test_small_input_skips_llm(self, mock_gen):
        result = compress("short text", "task")
        mock_gen.assert_not_called()
        assert "short text" in result

    @patch("core.agency.compressor.generate_local")
    def test_large_input_triggers_llm(self, mock_gen):
        mock_gen.return_value = {"response": "compressed"}
        big = " ".join([f"word{i}" for i in range(2000)])
        result = compress(big, "task")
        mock_gen.assert_called_once()
        assert result == "compressed"

    @patch("core.agency.compressor.generate_local")
    def test_rules_sufficient_skips_llm(self, mock_gen):
        data = {f"null_{i}": None for i in range(800)}
        data["keep"] = "value"
        raw = json.dumps(data)
        assert estimate_tokens(raw) > 1024
        result = compress(raw, "task")
        mock_gen.assert_not_called()
        parsed = json.loads(result)
        assert parsed == {"keep": "value"}

    @patch("core.agency.compressor.generate_local")
    def test_playwright_accessibility_snapshot(self, mock_gen):
        """Integration: realistic Playwright accessibility snapshot compression."""
        snapshot = json.dumps({
            "role": "WebArea",
            "name": "Dashboard",
            "children": [
                {"role": "heading", "name": "System Status", "level": 1, "children": None},
                {"role": "navigation", "name": "Main Nav", "children": [
                    {"role": "link", "name": f"Link {i}", "url": f"https://example.com/page{i}",
                     "description": None, "disabled": None, "checked": None}
                    for i in range(30)
                ]},
                {"role": "region", "name": "Content", "children": [
                    {"role": "paragraph", "name": "", "text": f"Paragraph {i} " * 20,
                     "metadata": None, "aria-hidden": None}
                    for i in range(20)
                ]},
            ],
            "metadata": None,
            "scrollPosition": None,
            "viewport": {"width": 1280, "height": 720},
        })
        original_tokens = estimate_tokens(snapshot)
        assert original_tokens > 1500
        result = RuleCompressor.compress(snapshot)
        compressed_tokens = estimate_tokens(result)
        # Nulls stripped, arrays truncated — significant reduction
        assert compressed_tokens < original_tokens * 0.5
        # Should still be valid JSON
        parsed = json.loads(result)
        assert parsed["role"] == "WebArea"
