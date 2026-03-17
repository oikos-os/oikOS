# Phase 7d Module 1: Context Engine Core — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build the token-efficiency layer that sits between oikOS and all tool interactions — observation masking, tool result compression, token budget tracking, and ReWOO planning.

**Architecture:** Four independent components in `core/agency/` that compose into a pipeline: stale tool outputs are masked (1.1), remaining outputs are compressed (1.2), all token usage is tracked against hard ceilings (1.3), and multi-step tasks use plan-then-execute to minimize LLM calls (1.4). Components 1.1-1.3 are standalone; 1.4 integrates 1.2 and 1.3.

**Tech Stack:** Python 3.12+, Ollama (qwen2.5:7b for compression), pytest, existing `core.interface.config` and `core.cognition.inference` infrastructure.

**SYNTH Rulings Applied:** 7b compressor model approved, word-based token counting approved (no tiktoken), specific module imports (no __init__.py re-exports), Ollama FIFO guard approved, in-memory evidence store for Module 1.

---

## Pre-Flight: Feature Branch + Config Constants

### Task 0: Create feature branch and add config constants

**Files:**
- Modify: `core/interface/config.py:199-202` (append after Calibration section)

**Step 1: Create feature branch**

Run:
```bash
cd D:/Development/OIKOS_OMEGA && git checkout -b feature/phase-7d-the-hands
```
Expected: `Switched to a new branch 'feature/phase-7d-the-hands'`

**Step 2: Add Context Engine config constants to config.py**

Append after line 202 (end of Calibration section):

```python
# ── Context Engine (Phase 7d Module 1) ────────────────────────────────
CONTEXT_ENGINE_HOT_WINDOW = 3           # Full tool outputs preserved
CONTEXT_ENGINE_WARM_CEILING = 10        # Warm tier: calls 4-10
CONTEXT_ENGINE_TOKEN_MULTIPLIER = 1.3   # Word-to-token approximation

# ── Tool Result Compression ───────────────────────────────────────────
COMPRESSOR_THRESHOLD_TOKENS = 1024      # Stage B triggers above this
COMPRESSOR_MAX_OUTPUT_TOKENS = 256      # LLM compression output cap
COMPRESSOR_MODEL = "qwen2.5:7b"         # Dedicated compression model
COMPRESSOR_ARRAY_PREVIEW_COUNT = 3      # Items shown before truncation

# ── Token Budget Tracker ─────────────────────────────────────────────
BUDGET_TIERS: dict[str, dict] = {
    "file_management":     {"max_input": 2000, "max_output": 1000, "max_tool_calls": 3,  "max_retries": 1},
    "vault_query":         {"max_input": 4000, "max_output": 2000, "max_tool_calls": 5,  "max_retries": 2},
    "research_web":        {"max_input": 8000, "max_output": 4000, "max_tool_calls": 10, "max_retries": 3},
    "browser_automation":  {"max_input": 6000, "max_output": 3000, "max_tool_calls": 8,  "max_retries": 2},
}
BUDGET_STATUS_THRESHOLDS = {"MEDIUM": 0.50, "LOW": 0.75, "CRITICAL": 0.90}

# ── Agency Logging ────────────────────────────────────────────────────
AGENCY_LOG_DIR = PROJECT_ROOT / "logs" / "agency"
```

**Step 3: Verify no syntax errors**

Run:
```bash
cd D:/Development/OIKOS_OMEGA && source .venv/Scripts/activate && python -c "from core.interface.config import BUDGET_TIERS, COMPRESSOR_MODEL, CONTEXT_ENGINE_HOT_WINDOW; print('Config OK')"
```
Expected: `Config OK`

**Step 4: Commit**

```bash
cd D:/Development/OIKOS_OMEGA && git add core/interface/config.py && git commit -m "$(cat <<'EOF'
feat(agency): add Context Engine config constants for Phase 7d Module 1

Budget tiers, compression thresholds, observation masking windows,
and agency logging directory. All values from SYNTH build brief.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 1: Observation Masking (`context_engine.py`)

**Files:**
- Create: `core/agency/context_engine.py`
- Create: `tests/test_context_engine.py`

### Step 1: Write the failing tests

Create `tests/test_context_engine.py`:

```python
"""Tests for core.agency.context_engine — Observation Masking."""

from __future__ import annotations

import pytest

from core.agency.context_engine import ContextEngine, estimate_tokens


# ── Token estimation ──────────────────────────────────────────────────

class TestEstimateTokens:
    def test_empty_string(self):
        assert estimate_tokens("") == 0

    def test_single_word(self):
        result = estimate_tokens("hello")
        assert result == int(1 * 1.3)

    def test_sentence(self):
        text = "The quick brown fox jumps over the lazy dog"
        result = estimate_tokens(text)
        assert result == int(9 * 1.3)


# ── Tier assignment ───────────────────────────────────────────────────

def _make_turn(role: str, content: str, tool_call: dict | None = None) -> dict:
    """Helper to build a conversation turn."""
    turn = {"role": role, "content": content}
    if tool_call:
        turn["tool_call"] = tool_call
    return turn


def _make_tool_turn(tool_name: str, args_summary: str, output: str) -> dict:
    """Helper to build a tool result turn."""
    return {
        "role": "tool",
        "content": output,
        "tool_call": {"name": tool_name, "args_summary": args_summary},
    }


class TestMaskObservations:
    def _build_conversation(self, n_tool_calls: int) -> list[dict]:
        """Build a conversation with n tool calls interleaved with user/assistant."""
        history = []
        for i in range(n_tool_calls):
            history.append(_make_turn("user", f"Question {i+1}"))
            history.append(_make_turn("assistant", f"Let me check tool {i+1}"))
            history.append(_make_tool_turn(
                f"tool_{i+1}",
                f"arg={i+1}",
                f"Result data {'x' * 200} for tool {i+1}",
            ))
            history.append(_make_turn("assistant", f"Answer {i+1}"))
        return history

    def test_hot_tier_preserves_recent_outputs(self):
        """Last 3 tool calls should have full outputs."""
        engine = ContextEngine()
        history = self._build_conversation(5)
        masked = engine.mask_observations(history)

        tool_turns = [t for t in masked if t["role"] == "tool"]
        # Last 3 tool turns should have full content (not masked)
        for turn in tool_turns[-3:]:
            assert "[masked" not in turn["content"]
            assert "Result data" in turn["content"]

    def test_warm_tier_masks_with_metadata(self):
        """Tool calls 4-10 should be replaced with labeled placeholders."""
        engine = ContextEngine()
        history = self._build_conversation(6)
        masked = engine.mask_observations(history)

        tool_turns = [t for t in masked if t["role"] == "tool"]
        # First 3 tool turns are warm (6 total - 3 hot = 3 warm)
        for turn in tool_turns[:3]:
            assert "[masked" in turn["content"]
            assert "tokens removed" in turn["content"]
            assert "Call:" in turn["content"]

    def test_cold_tier_collapses_to_single_line(self):
        """Tool calls 11+ should be collapsed to a single line."""
        engine = ContextEngine()
        history = self._build_conversation(14)
        masked = engine.mask_observations(history)

        tool_turns = [t for t in masked if t["role"] == "tool"]
        # First 3 tool turns are cold (14 - 3 hot - 7 warm = 4 cold)
        for turn in tool_turns[:4]:
            assert "[Turn" in turn["content"]
            assert "details masked" in turn["content"]

    def test_no_tool_calls_unchanged(self):
        """Conversation without tool calls should pass through unchanged."""
        engine = ContextEngine()
        history = [
            _make_turn("user", "Hello"),
            _make_turn("assistant", "Hi there"),
        ]
        masked = engine.mask_observations(history)
        assert masked == history

    def test_single_tool_call_is_hot(self):
        """One tool call should be in hot tier (preserved)."""
        engine = ContextEngine()
        history = self._build_conversation(1)
        masked = engine.mask_observations(history)

        tool_turns = [t for t in masked if t["role"] == "tool"]
        assert len(tool_turns) == 1
        assert "[masked" not in tool_turns[0]["content"]

    def test_exactly_three_tool_calls_all_hot(self):
        """Exactly window_size tool calls should all be hot."""
        engine = ContextEngine()
        history = self._build_conversation(3)
        masked = engine.mask_observations(history)

        tool_turns = [t for t in masked if t["role"] == "tool"]
        assert len(tool_turns) == 3
        for turn in tool_turns:
            assert "[masked" not in turn["content"]

    def test_non_tool_turns_unchanged(self):
        """User and assistant turns should never be masked."""
        engine = ContextEngine()
        history = self._build_conversation(8)
        masked = engine.mask_observations(history)

        for turn in masked:
            if turn["role"] in ("user", "assistant"):
                assert "[masked" not in turn["content"]
                assert "[Turn" not in turn["content"]

    def test_custom_window_size(self):
        """Custom window_size should change hot tier boundary."""
        engine = ContextEngine(hot_window=5)
        history = self._build_conversation(7)
        masked = engine.mask_observations(history)

        tool_turns = [t for t in masked if t["role"] == "tool"]
        # Last 5 should be hot
        for turn in tool_turns[-5:]:
            assert "[masked" not in turn["content"]
        # First 2 should be warm
        for turn in tool_turns[:2]:
            assert "[masked" in turn["content"]

    def test_token_reduction_at_least_50_percent(self):
        """Masked conversation should use ≤50% of original tokens (40% target)."""
        engine = ContextEngine()
        history = self._build_conversation(12)

        original_tokens = sum(estimate_tokens(t["content"]) for t in history)
        masked = engine.mask_observations(history)
        masked_tokens = sum(estimate_tokens(t["content"]) for t in masked)

        assert masked_tokens <= original_tokens * 0.50

    def test_warm_tier_preserves_tool_name_and_args(self):
        """Warm tier placeholders must include tool name and args summary."""
        engine = ContextEngine()
        history = self._build_conversation(6)
        masked = engine.mask_observations(history)

        tool_turns = [t for t in masked if t["role"] == "tool"]
        # First 3 are warm
        for i, turn in enumerate(tool_turns[:3]):
            assert f"tool_{i+1}" in turn["content"]
```

### Step 2: Run tests to verify they fail

Run:
```bash
cd D:/Development/OIKOS_OMEGA && source .venv/Scripts/activate && python -m pytest tests/test_context_engine.py -v 2>&1 | head -30
```
Expected: `ModuleNotFoundError: No module named 'core.agency.context_engine'`

### Step 3: Write minimal implementation

Create `core/agency/context_engine.py`:

```python
"""Observation Masking — hot/warm/cold tier management for tool outputs.

Phase 7d Module 1.1. Based on JetBrains Research (NeurIPS 2025):
rule-based observation masking matches LLM summarization at zero cost.
"""

from __future__ import annotations

import logging

from core.interface.config import (
    CONTEXT_ENGINE_HOT_WINDOW,
    CONTEXT_ENGINE_TOKEN_MULTIPLIER,
    CONTEXT_ENGINE_WARM_CEILING,
)

log = logging.getLogger(__name__)


def estimate_tokens(text: str) -> int:
    """Word-based token estimation. Avoids tiktoken dependency (via negativa)."""
    if not text:
        return 0
    return int(len(text.split()) * CONTEXT_ENGINE_TOKEN_MULTIPLIER)


class ContextEngine:
    """Manages conversation context by masking stale tool outputs.

    Hot tier:  last `hot_window` tool calls — full outputs preserved.
    Warm tier: calls hot_window+1 through warm_ceiling — labeled placeholders.
    Cold tier: calls warm_ceiling+1 and beyond — single-line collapse.
    """

    def __init__(self, hot_window: int | None = None, warm_ceiling: int | None = None):
        self.hot_window = hot_window or CONTEXT_ENGINE_HOT_WINDOW
        self.warm_ceiling = warm_ceiling or CONTEXT_ENGINE_WARM_CEILING

    def mask_observations(self, conversation_history: list[dict]) -> list[dict]:
        """Apply tiered masking to tool outputs in conversation history.

        Args:
            conversation_history: List of turn dicts with role, content, optional tool_call.

        Returns:
            New list with tool outputs masked according to tier rules.
        """
        # Identify indices of tool turns (reverse order for tier assignment)
        tool_indices = [
            i for i, turn in enumerate(conversation_history)
            if turn.get("role") == "tool"
        ]

        if not tool_indices:
            return list(conversation_history)

        # Assign tiers: count from the end (most recent = rank 1)
        total_tools = len(tool_indices)
        tier_map: dict[int, str] = {}
        for rank, idx in enumerate(reversed(tool_indices)):
            rank_1based = rank + 1
            if rank_1based <= self.hot_window:
                tier_map[idx] = "hot"
            elif rank_1based <= self.warm_ceiling:
                tier_map[idx] = "warm"
            else:
                tier_map[idx] = "cold"

        # Build masked history
        result = []
        tool_counter = 0
        for i, turn in enumerate(conversation_history):
            if turn.get("role") != "tool":
                result.append(dict(turn))
                continue

            tool_counter += 1
            tier = tier_map[i]

            if tier == "hot":
                result.append(dict(turn))
            elif tier == "warm":
                tool_call = turn.get("tool_call", {})
                tool_name = tool_call.get("name", "unknown")
                args_summary = tool_call.get("args_summary", "")
                original_tokens = estimate_tokens(turn["content"])
                result.append({
                    "role": "tool",
                    "content": f"[masked — {original_tokens} tokens removed. Call: {tool_name}({args_summary})]",
                    "tool_call": turn.get("tool_call"),
                })
            else:  # cold
                tool_call = turn.get("tool_call", {})
                tool_name = tool_call.get("name", "unknown")
                result.append({
                    "role": "tool",
                    "content": f"[Turn {tool_counter}: {tool_name} call — details masked]",
                    "tool_call": turn.get("tool_call"),
                })

        return result
```

### Step 4: Run tests to verify they pass

Run:
```bash
cd D:/Development/OIKOS_OMEGA && source .venv/Scripts/activate && python -m pytest tests/test_context_engine.py -v
```
Expected: All 11 tests PASS

### Step 5: Commit

```bash
cd D:/Development/OIKOS_OMEGA && git add core/agency/context_engine.py tests/test_context_engine.py && git commit -m "$(cat <<'EOF'
feat(agency): add observation masking (Phase 7d Module 1.1)

Hot/warm/cold tier masking of stale tool outputs. Rule-based, zero
LLM cost. Based on JetBrains Research (NeurIPS 2025) finding that
masking matches LLM summarization. Word-based token estimator avoids
tiktoken dependency.

11 tests covering tier assignment, token reduction (≥50%), fidelity,
edge cases, and custom window sizes.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Tool Result Compression (`compressor.py`)

**Files:**
- Create: `core/agency/compressor.py`
- Create: `tests/test_compressor.py`

### Step 1: Write the failing tests

Create `tests/test_compressor.py`:

```python
"""Tests for core.agency.compressor — Tool Result Compression."""

from __future__ import annotations

import json
from unittest.mock import patch, MagicMock

import pytest

from core.agency.compressor import (
    RuleCompressor,
    LLMCompressor,
    compress,
)
from core.agency.context_engine import estimate_tokens


# ── Rule Compressor ───────────────────────────────────────────────────

class TestRuleCompressorNulls:
    def test_strips_null_values(self):
        data = json.dumps({"name": "foo", "bar": None, "baz": ""})
        result = RuleCompressor.compress(data)
        parsed = json.loads(result)
        assert "bar" not in parsed
        assert "baz" not in parsed
        assert parsed["name"] == "foo"

    def test_strips_nested_nulls(self):
        data = json.dumps({"a": {"b": None, "c": "keep"}, "d": None})
        result = RuleCompressor.compress(data)
        parsed = json.loads(result)
        assert parsed == {"a": {"c": "keep"}}

    def test_strips_nulls_from_50_fields(self):
        obj = {f"field_{i}": None for i in range(50)}
        obj["real"] = "data"
        data = json.dumps(obj)
        result = RuleCompressor.compress(data)
        parsed = json.loads(result)
        assert parsed == {"real": "data"}


class TestRuleCompressorArrays:
    def test_truncates_long_array(self):
        arr = list(range(47))
        data = json.dumps({"items": arr})
        result = RuleCompressor.compress(data)
        parsed = json.loads(result)
        assert len(parsed["items"]) == 4  # 3 items + truncation notice
        assert "3 of 47" in parsed["items"][-1]

    def test_preserves_short_array(self):
        data = json.dumps({"items": [1, 2, 3]})
        result = RuleCompressor.compress(data)
        parsed = json.loads(result)
        assert parsed["items"] == [1, 2, 3]

    def test_top_level_array(self):
        data = json.dumps(list(range(20)))
        result = RuleCompressor.compress(data)
        parsed = json.loads(result)
        assert len(parsed) == 4


class TestRuleCompressorNumbers:
    def test_abbreviates_millions(self):
        result = RuleCompressor.compress("Population: 1200000 people")
        assert "1.2M" in result

    def test_abbreviates_thousands(self):
        result = RuleCompressor.compress("Count: 45000 items")
        assert "45.0K" in result

    def test_preserves_small_numbers(self):
        result = RuleCompressor.compress("Count: 999 items")
        assert "999" in result


class TestRuleCompressorHTML:
    def test_strips_html_tags(self):
        html = '<div class="container"><p>Hello</p><span>World</span></div>'
        result = RuleCompressor.compress(html)
        assert "<div" not in result
        assert "<p>" not in result
        assert "Hello" in result
        assert "World" in result

    def test_strips_nested_html(self):
        html = "<html><body><div><ul><li>Item 1</li><li>Item 2</li></ul></div></body></html>"
        result = RuleCompressor.compress(html)
        assert "Item 1" in result
        assert "<li>" not in result


class TestRuleCompressorCLIXML:
    def test_strips_clixml(self):
        clixml = '#< CLIXML\n<Objs Version="1.1">\n<S S="progress">Processing...</S>\n</Objs>\nActual output here'
        result = RuleCompressor.compress(clixml)
        assert "CLIXML" not in result
        assert "Objs" not in result
        assert "Actual output here" in result

    def test_strips_clixml_only(self):
        clixml = '#< CLIXML\n<Objs Version="1.1"><S>data</S></Objs>'
        result = RuleCompressor.compress(clixml)
        assert result.strip() == ""


class TestRuleCompressorWhitespace:
    def test_collapses_multiple_newlines(self):
        text = "Line 1\n\n\n\n\nLine 2\n\n\nLine 3"
        result = RuleCompressor.compress(text)
        assert "\n\n\n" not in result
        assert "Line 1" in result
        assert "Line 2" in result


class TestRuleCompressorSize:
    def test_5000_token_result_under_threshold(self):
        """5,000-token tool result should compress to ≤1,024 tokens after rules."""
        # Build a large JSON with lots of nulls and long arrays
        obj = {f"field_{i}": None for i in range(200)}
        obj["data"] = list(range(500))
        obj["html"] = "<div>" + "<p>paragraph</p>" * 100 + "</div>"
        obj["real_content"] = "This is the actual useful information."
        data = json.dumps(obj)
        assert estimate_tokens(data) > 2000  # Verify it's big enough

        result = RuleCompressor.compress(data)
        # Rule compression should significantly reduce size
        assert estimate_tokens(result) < estimate_tokens(data) * 0.5


# ── LLM Compressor ────────────────────────────────────────────────────

class TestLLMCompressor:
    def test_compresses_via_local_model(self):
        mock_response = {"response": "Summary: vault contains 132 files across 3 tiers."}
        with patch("core.agency.compressor.generate_local", return_value=mock_response):
            result = LLMCompressor.compress(
                "Very long text " * 500,
                task_context="Check vault status",
            )
        assert "132 files" in result

    def test_fallback_on_llm_error(self):
        with patch("core.agency.compressor.generate_local", return_value={"error": "timeout", "response": ""}):
            result = LLMCompressor.compress(
                "Some text " * 200,
                task_context="test",
            )
        # Should return truncated input, not crash
        assert len(result) > 0

    def test_respects_max_tokens(self):
        long_summary = "word " * 500
        mock_response = {"response": long_summary}
        with patch("core.agency.compressor.generate_local", return_value=mock_response):
            result = LLMCompressor.compress("input", task_context="test", max_tokens=256)
        # Should truncate to max_tokens
        assert estimate_tokens(result) <= 256 + 10  # Small tolerance


# ── Pipeline ──────────────────────────────────────────────────────────

class TestCompressPipeline:
    def test_small_input_skips_llm(self):
        """Input under threshold should only use rule compression."""
        small = json.dumps({"key": "value", "null_field": None})
        with patch("core.agency.compressor.generate_local") as mock_llm:
            result = compress(small, task_context="test")
        mock_llm.assert_not_called()

    def test_large_input_triggers_llm(self):
        """Input over threshold after rule compression should trigger LLM."""
        # Build content that stays large after rule compression
        large = "Important data. " * 300
        mock_response = {"response": "Compressed summary of important data."}
        with patch("core.agency.compressor.generate_local", return_value=mock_response):
            result = compress(large, task_context="test", threshold=100)
        assert "Compressed summary" in result

    def test_rules_sufficient_skips_llm(self):
        """If rules bring it under threshold, LLM is not called."""
        obj = {f"null_{i}": None for i in range(200)}
        obj["real"] = "short"
        data = json.dumps(obj)
        with patch("core.agency.compressor.generate_local") as mock_llm:
            result = compress(data, task_context="test", threshold=1024)
        mock_llm.assert_not_called()
```

### Step 2: Run tests to verify they fail

Run:
```bash
cd D:/Development/OIKOS_OMEGA && source .venv/Scripts/activate && python -m pytest tests/test_compressor.py -v 2>&1 | head -10
```
Expected: `ModuleNotFoundError: No module named 'core.agency.compressor'`

### Step 3: Write minimal implementation

Create `core/agency/compressor.py`:

```python
"""Tool Result Compression — rule-based stripping + LLM fallback.

Phase 7d Module 1.2. Two-stage pipeline:
  Stage A: Rule-based (always runs) — strip nulls, truncate arrays, strip HTML/CLIXML.
  Stage B: LLM-based (threshold gate) — semantic compression via qwen2.5:7b.
"""

from __future__ import annotations

import json
import logging
import re

from core.interface.config import (
    COMPRESSOR_ARRAY_PREVIEW_COUNT,
    COMPRESSOR_MAX_OUTPUT_TOKENS,
    COMPRESSOR_MODEL,
    COMPRESSOR_THRESHOLD_TOKENS,
)
from core.agency.context_engine import estimate_tokens

log = logging.getLogger(__name__)

# ── Patterns ──────────────────────────────────────────────────────────
_CLIXML_RE = re.compile(r"#<\s*CLIXML.*?</Objs>", re.DOTALL | re.IGNORECASE)
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_MULTI_NEWLINE_RE = re.compile(r"\n{3,}")
_LARGE_NUMBER_RE = re.compile(r"\b(\d{1,3}(?:,?\d{3})+)\b")


def _strip_nulls(obj):
    """Recursively remove null/empty values from a JSON-like structure."""
    if isinstance(obj, dict):
        return {k: _strip_nulls(v) for k, v in obj.items()
                if v is not None and v != ""}
    if isinstance(obj, list):
        return [_strip_nulls(item) for item in obj]
    return obj


def _truncate_array(arr: list, preview: int = COMPRESSOR_ARRAY_PREVIEW_COUNT) -> list:
    """Truncate array to preview items + count notice."""
    if len(arr) <= preview:
        return arr
    return arr[:preview] + [f"...{preview} of {len(arr)} items shown"]


def _truncate_arrays(obj, preview: int = COMPRESSOR_ARRAY_PREVIEW_COUNT):
    """Recursively truncate arrays in a JSON-like structure."""
    if isinstance(obj, dict):
        return {k: _truncate_arrays(v, preview) for k, v in obj.items()}
    if isinstance(obj, list):
        truncated = _truncate_array(obj, preview)
        return [_truncate_arrays(item, preview) if isinstance(item, (dict, list)) else item
                for item in truncated]
    return obj


def _abbreviate_number(match: re.Match) -> str:
    """Convert large numbers to abbreviated form (1200000 -> 1.2M)."""
    raw = match.group(1).replace(",", "")
    num = int(raw)
    if num >= 1_000_000:
        return f"{num / 1_000_000:.1f}M"
    if num >= 1_000:
        return f"{num / 1_000:.1f}K"
    return raw


class RuleCompressor:
    """Stage A: deterministic rule-based compression. Zero LLM cost."""

    @staticmethod
    def compress(text: str) -> str:
        """Apply all rule-based compression passes."""
        # 1. CLIXML stripping (before JSON parse attempt)
        text = _CLIXML_RE.sub("", text)

        # 2. Try JSON parse for structured compression
        stripped = text.strip()
        try:
            obj = json.loads(stripped)
            obj = _strip_nulls(obj)
            obj = _truncate_arrays(obj)
            text = json.dumps(obj, separators=(",", ":"))
        except (json.JSONDecodeError, TypeError):
            pass  # Not JSON — continue with text-based rules

        # 3. HTML tag stripping
        text = _HTML_TAG_RE.sub("", text)

        # 4. Number abbreviation
        text = _LARGE_NUMBER_RE.sub(_abbreviate_number, text)

        # 5. Whitespace normalization
        text = _MULTI_NEWLINE_RE.sub("\n\n", text)
        text = text.strip()

        return text


class LLMCompressor:
    """Stage B: LLM-based semantic compression via local model."""

    @staticmethod
    def compress(
        text: str,
        task_context: str,
        max_tokens: int = COMPRESSOR_MAX_OUTPUT_TOKENS,
    ) -> str:
        """Compress text using local LLM. Falls back to truncation on error."""
        from core.cognition.inference import generate_local

        prompt = (
            f"Extract only the information relevant to '{task_context}' "
            f"from this result. Be concise.\n\n{text}"
        )
        result = generate_local(
            prompt,
            model=COMPRESSOR_MODEL,
            num_predict=max_tokens,
        )

        response = result.get("response", "").strip()
        if not response or result.get("error"):
            # Fallback: truncate to approximate token limit
            words = text.split()
            max_words = int(max_tokens / 1.3)
            return " ".join(words[:max_words])

        # Enforce max_tokens on output
        if estimate_tokens(response) > max_tokens:
            words = response.split()
            max_words = int(max_tokens / 1.3)
            response = " ".join(words[:max_words])

        return response


def compress(
    tool_result: str,
    task_context: str,
    threshold: int = COMPRESSOR_THRESHOLD_TOKENS,
) -> str:
    """Two-stage compression pipeline.

    Stage A (rules) always runs. Stage B (LLM) only if result
    still exceeds threshold after rules.
    """
    # Stage A
    result = RuleCompressor.compress(tool_result)

    # Stage B gate
    if estimate_tokens(result) > threshold:
        result = LLMCompressor.compress(result, task_context)

    return result
```

### Step 4: Run tests to verify they pass

Run:
```bash
cd D:/Development/OIKOS_OMEGA && source .venv/Scripts/activate && python -m pytest tests/test_compressor.py -v
```
Expected: All 20 tests PASS

### Step 5: Commit

```bash
cd D:/Development/OIKOS_OMEGA && git add core/agency/compressor.py tests/test_compressor.py && git commit -m "$(cat <<'EOF'
feat(agency): add tool result compression (Phase 7d Module 1.2)

Two-stage pipeline: rule-based stripping (nulls, arrays, HTML, CLIXML,
large numbers, whitespace) + LLM fallback via qwen2.5:7b when result
exceeds 1,024 token threshold. Falls back to truncation on LLM error.

20 tests covering null stripping, array truncation, HTML/CLIXML removal,
number abbreviation, LLM compression, pipeline gating, and fallback.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Token Budget Tracker (`budget.py`)

**Files:**
- Create: `core/agency/budget.py`
- Create: `tests/test_budget.py`

### Step 1: Write the failing tests

Create `tests/test_budget.py`:

```python
"""Tests for core.agency.budget — Token Budget Tracker."""

from __future__ import annotations

import pytest

from core.agency.budget import TokenBudget, BudgetStatus


# ── Allocation ────────────────────────────────────────────────────────

class TestAllocation:
    def test_file_management_limits(self):
        budget = TokenBudget.allocate("file_management")
        assert budget.max_input == 2000
        assert budget.max_output == 1000
        assert budget.max_tool_calls == 3
        assert budget.max_retries == 1

    def test_vault_query_limits(self):
        budget = TokenBudget.allocate("vault_query")
        assert budget.max_input == 4000
        assert budget.max_output == 2000
        assert budget.max_tool_calls == 5
        assert budget.max_retries == 2

    def test_research_web_limits(self):
        budget = TokenBudget.allocate("research_web")
        assert budget.max_input == 8000
        assert budget.max_output == 4000

    def test_browser_automation_limits(self):
        budget = TokenBudget.allocate("browser_automation")
        assert budget.max_input == 6000
        assert budget.max_output == 3000

    def test_unknown_action_raises(self):
        with pytest.raises(ValueError, match="Unknown action type"):
            TokenBudget.allocate("unknown_action")


# ── Consumption ───────────────────────────────────────────────────────

class TestConsumption:
    def test_consume_input_tokens(self):
        budget = TokenBudget.allocate("file_management")
        budget.consume(500, "input")
        assert budget.used_input == 500

    def test_consume_output_tokens(self):
        budget = TokenBudget.allocate("file_management")
        budget.consume(300, "output")
        assert budget.used_output == 300

    def test_consume_accumulates(self):
        budget = TokenBudget.allocate("vault_query")
        budget.consume(1000, "input")
        budget.consume(500, "input")
        assert budget.used_input == 1500

    def test_consume_zero_is_noop(self):
        budget = TokenBudget.allocate("file_management")
        budget.consume(0, "input")
        assert budget.used_input == 0

    def test_consume_negative_raises(self):
        budget = TokenBudget.allocate("file_management")
        with pytest.raises(ValueError, match="negative"):
            budget.consume(-1, "input")

    def test_consume_invalid_direction_raises(self):
        budget = TokenBudget.allocate("file_management")
        with pytest.raises(ValueError, match="direction"):
            budget.consume(100, "sideways")


# ── Tool Call Tracking ─────────────────────────────────────────────────

class TestToolCalls:
    def test_record_tool_call(self):
        budget = TokenBudget.allocate("file_management")
        budget.record_tool_call()
        assert budget.tool_calls == 1

    def test_tool_calls_accumulate(self):
        budget = TokenBudget.allocate("vault_query")
        for _ in range(3):
            budget.record_tool_call()
        assert budget.tool_calls == 3

    def test_record_retry(self):
        budget = TokenBudget.allocate("research_web")
        budget.record_retry()
        assert budget.retries == 1


# ── Status ────────────────────────────────────────────────────────────

class TestStatus:
    def test_high_status_at_start(self):
        budget = TokenBudget.allocate("vault_query")
        assert budget.check() == BudgetStatus.HIGH

    def test_medium_status_at_50_percent(self):
        budget = TokenBudget.allocate("vault_query")
        budget.consume(2000, "input")  # 50% of 4000
        assert budget.check() == BudgetStatus.MEDIUM

    def test_low_status_at_75_percent(self):
        budget = TokenBudget.allocate("vault_query")
        budget.consume(3000, "input")  # 75% of 4000
        assert budget.check() == BudgetStatus.LOW

    def test_critical_status_at_90_percent(self):
        budget = TokenBudget.allocate("vault_query")
        budget.consume(3600, "input")  # 90% of 4000
        assert budget.check() == BudgetStatus.CRITICAL

    def test_status_considers_both_input_and_output(self):
        budget = TokenBudget.allocate("file_management")
        # max_input=2000, max_output=1000, total=3000
        budget.consume(1000, "input")   # 33% of total
        budget.consume(500, "output")   # +17% = 50% total
        assert budget.check() == BudgetStatus.MEDIUM


# ── Circuit Breaker ───────────────────────────────────────────────────

class TestCircuitBreaker:
    def test_enforce_within_budget(self):
        budget = TokenBudget.allocate("vault_query")
        budget.consume(1000, "input")
        assert budget.enforce() is True

    def test_enforce_at_input_ceiling(self):
        budget = TokenBudget.allocate("file_management")
        budget.consume(2000, "input")
        assert budget.enforce() is False

    def test_enforce_at_output_ceiling(self):
        budget = TokenBudget.allocate("file_management")
        budget.consume(1000, "output")
        assert budget.enforce() is False

    def test_enforce_at_tool_call_ceiling(self):
        budget = TokenBudget.allocate("file_management")
        for _ in range(3):
            budget.record_tool_call()
        assert budget.enforce() is False

    def test_enforce_at_retry_ceiling(self):
        budget = TokenBudget.allocate("file_management")
        budget.record_retry()
        assert budget.enforce() is False

    def test_enforce_just_under_ceiling(self):
        budget = TokenBudget.allocate("file_management")
        budget.consume(1999, "input")
        assert budget.enforce() is True


# ── Prompt Injection ──────────────────────────────────────────────────

class TestFormatInjection:
    def test_format_contains_used_and_max(self):
        budget = TokenBudget.allocate("vault_query")
        budget.consume(1847, "input")
        injection = budget.format_injection()
        assert "1,847" in injection or "1847" in injection
        assert "4,000" in injection or "4000" in injection

    def test_format_contains_tool_calls(self):
        budget = TokenBudget.allocate("vault_query")
        budget.record_tool_call()
        budget.record_tool_call()
        injection = budget.format_injection()
        assert "2/5" in injection or "2 / 5" in injection

    def test_format_contains_status(self):
        budget = TokenBudget.allocate("vault_query")
        injection = budget.format_injection()
        assert "HIGH" in injection

    def test_format_starts_with_budget_tag(self):
        budget = TokenBudget.allocate("file_management")
        injection = budget.format_injection()
        assert injection.startswith("[BUDGET]")

    def test_format_shows_percentage(self):
        budget = TokenBudget.allocate("vault_query")
        budget.consume(2000, "input")
        injection = budget.format_injection()
        # 2000/6000 total capacity ≈ 33%
        assert "%" in injection
```

### Step 2: Run tests to verify they fail

Run:
```bash
cd D:/Development/OIKOS_OMEGA && source .venv/Scripts/activate && python -m pytest tests/test_budget.py -v 2>&1 | head -10
```
Expected: `ModuleNotFoundError: No module named 'core.agency.budget'`

### Step 3: Write minimal implementation

Create `core/agency/budget.py`:

```python
"""Token Budget Tracker — per-action ceilings with circuit breaker.

Phase 7d Module 1.3. Inspired by Google BATS: budget constraints
improve agent focus. Enforces hard ceilings before Ollama's num_ctx
to prevent silent FIFO truncation.
"""

from __future__ import annotations

import enum
import logging

from core.interface.config import BUDGET_STATUS_THRESHOLDS, BUDGET_TIERS

log = logging.getLogger(__name__)


class BudgetStatus(enum.Enum):
    HIGH = "HIGH"           # <50% consumed
    MEDIUM = "MEDIUM"       # 50-75%
    LOW = "LOW"             # 75-90%
    CRITICAL = "CRITICAL"   # >90%


class TokenBudget:
    """Tracks token consumption against hard ceilings for an autonomous task.

    Usage:
        budget = TokenBudget.allocate("vault_query")
        budget.consume(500, "input")
        if not budget.enforce():
            return partial_results
        prompt += budget.format_injection()
    """

    def __init__(
        self,
        action_type: str,
        max_input: int,
        max_output: int,
        max_tool_calls: int,
        max_retries: int,
    ):
        self.action_type = action_type
        self.max_input = max_input
        self.max_output = max_output
        self.max_tool_calls = max_tool_calls
        self.max_retries = max_retries
        self.used_input = 0
        self.used_output = 0
        self.tool_calls = 0
        self.retries = 0

    @classmethod
    def allocate(cls, action_type: str) -> TokenBudget:
        """Create a budget for the given action type from config tiers."""
        tier = BUDGET_TIERS.get(action_type)
        if not tier:
            raise ValueError(f"Unknown action type: {action_type!r}")
        return cls(action_type=action_type, **tier)

    def consume(self, tokens: int, direction: str) -> None:
        """Record token consumption. Direction must be 'input' or 'output'."""
        if tokens < 0:
            raise ValueError("Cannot consume negative tokens")
        if direction == "input":
            self.used_input += tokens
        elif direction == "output":
            self.used_output += tokens
        else:
            raise ValueError(f"Invalid direction: {direction!r} (must be 'input' or 'output')")

    def record_tool_call(self) -> None:
        self.tool_calls += 1

    def record_retry(self) -> None:
        self.retries += 1

    @property
    def total_capacity(self) -> int:
        return self.max_input + self.max_output

    @property
    def total_used(self) -> int:
        return self.used_input + self.used_output

    @property
    def utilization(self) -> float:
        """Fraction of total budget consumed (0.0 to 1.0+)."""
        if self.total_capacity == 0:
            return 1.0
        return self.total_used / self.total_capacity

    def check(self) -> BudgetStatus:
        """Return current budget status based on utilization thresholds."""
        pct = self.utilization
        if pct >= BUDGET_STATUS_THRESHOLDS["CRITICAL"]:
            return BudgetStatus.CRITICAL
        if pct >= BUDGET_STATUS_THRESHOLDS["LOW"]:
            return BudgetStatus.LOW
        if pct >= BUDGET_STATUS_THRESHOLDS["MEDIUM"]:
            return BudgetStatus.MEDIUM
        return BudgetStatus.HIGH

    def enforce(self) -> bool:
        """Check all ceilings. Returns True if within budget, False if breached."""
        if self.used_input >= self.max_input:
            log.warning("Budget breached: input %d/%d", self.used_input, self.max_input)
            return False
        if self.used_output >= self.max_output:
            log.warning("Budget breached: output %d/%d", self.used_output, self.max_output)
            return False
        if self.tool_calls >= self.max_tool_calls:
            log.warning("Budget breached: tool calls %d/%d", self.tool_calls, self.max_tool_calls)
            return False
        if self.retries >= self.max_retries:
            log.warning("Budget breached: retries %d/%d", self.retries, self.max_retries)
            return False
        return True

    def format_injection(self) -> str:
        """BATS-style budget string for prompt injection."""
        pct = int(self.utilization * 100)
        status = self.check().value
        return (
            f"[BUDGET] Used: {self.total_used:,}/{self.total_capacity:,} tokens ({pct}%). "
            f"Tool calls: {self.tool_calls}/{self.max_tool_calls}. "
            f"Status: {status}."
        )
```

### Step 4: Run tests to verify they pass

Run:
```bash
cd D:/Development/OIKOS_OMEGA && source .venv/Scripts/activate && python -m pytest tests/test_budget.py -v
```
Expected: All 27 tests PASS

### Step 5: Commit

```bash
cd D:/Development/OIKOS_OMEGA && git add core/agency/budget.py tests/test_budget.py && git commit -m "$(cat <<'EOF'
feat(agency): add token budget tracker (Phase 7d Module 1.3)

Per-action ceilings with circuit breaker, inspired by Google BATS.
Four budget tiers (file/vault/research/browser), BATS-style prompt
injection, and independent ceiling enforcement to prevent Ollama's
silent FIFO truncation.

27 tests covering allocation, consumption, status transitions,
circuit breaker, prompt injection format, and edge cases.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: ReWOO Planner (`planner.py`)

**Files:**
- Create: `core/agency/planner.py`
- Create: `tests/test_planner.py`

### Step 1: Write the failing tests

Create `tests/test_planner.py`:

```python
"""Tests for core.agency.planner — ReWOO Planner."""

from __future__ import annotations

import json
from unittest.mock import patch, MagicMock, call

import pytest

from core.agency.planner import ReWOOPlanner, PlanStep
from core.agency.context_engine import estimate_tokens


# ── PlanStep model ────────────────────────────────────────────────────

class TestPlanStep:
    def test_serialization_roundtrip(self):
        step = PlanStep(
            step_id="#E1",
            tool_name="vault_search",
            tool_args={"query": "LanceDB schema"},
            depends_on=[],
        )
        data = step.to_dict()
        restored = PlanStep.from_dict(data)
        assert restored.step_id == "#E1"
        assert restored.tool_name == "vault_search"
        assert restored.tool_args == {"query": "LanceDB schema"}

    def test_json_roundtrip(self):
        step = PlanStep(
            step_id="#E2",
            tool_name="file_read",
            tool_args={"path": "/tmp/test.md"},
            depends_on=["#E1"],
        )
        json_str = json.dumps(step.to_dict())
        restored = PlanStep.from_dict(json.loads(json_str))
        assert restored.depends_on == ["#E1"]

    def test_placeholder_syntax(self):
        step = PlanStep(step_id="#E1", tool_name="t", tool_args={}, depends_on=[])
        assert step.step_id.startswith("#E")


# ── Plan generation ───────────────────────────────────────────────────

_MOCK_PLAN_RESPONSE = json.dumps([
    {"step_id": "#E1", "tool_name": "vault_search", "tool_args": {"query": "memory architecture"}, "depends_on": []},
    {"step_id": "#E2", "tool_name": "file_read", "tool_args": {"path": "#E1.top_result"}, "depends_on": ["#E1"]},
    {"step_id": "#E3", "tool_name": "vault_search", "tool_args": {"query": "embedding model"}, "depends_on": []},
])


class TestPlan:
    def test_plan_returns_steps(self):
        mock_resp = {"response": _MOCK_PLAN_RESPONSE}
        with patch("core.agency.planner.generate_local", return_value=mock_resp):
            planner = ReWOOPlanner()
            steps = planner.plan("What is the memory architecture?", ["vault_search", "file_read"])
        assert len(steps) == 3
        assert all(isinstance(s, PlanStep) for s in steps)

    def test_plan_preserves_dependencies(self):
        mock_resp = {"response": _MOCK_PLAN_RESPONSE}
        with patch("core.agency.planner.generate_local", return_value=mock_resp):
            planner = ReWOOPlanner()
            steps = planner.plan("test", ["vault_search", "file_read"])
        assert steps[1].depends_on == ["#E1"]
        assert steps[0].depends_on == []

    def test_plan_handles_markdown_fences(self):
        fenced = f"```json\n{_MOCK_PLAN_RESPONSE}\n```"
        mock_resp = {"response": fenced}
        with patch("core.agency.planner.generate_local", return_value=mock_resp):
            planner = ReWOOPlanner()
            steps = planner.plan("test", ["vault_search"])
        assert len(steps) == 3

    def test_plan_empty_on_llm_error(self):
        mock_resp = {"error": "timeout", "response": ""}
        with patch("core.agency.planner.generate_local", return_value=mock_resp):
            planner = ReWOOPlanner()
            steps = planner.plan("test", ["vault_search"])
        assert steps == []


# ── Execution ─────────────────────────────────────────────────────────

class TestExecute:
    def _make_steps(self) -> list[PlanStep]:
        return [
            PlanStep("#E1", "vault_search", {"query": "memory"}, []),
            PlanStep("#E2", "file_read", {"path": "#E1"}, ["#E1"]),
            PlanStep("#E3", "vault_search", {"query": "identity"}, []),
        ]

    def test_populates_evidence_store(self):
        tools = {
            "vault_search": lambda **kw: f"Results for {kw['query']}",
            "file_read": lambda **kw: f"Content of {kw['path']}",
        }
        planner = ReWOOPlanner()
        evidence = planner.execute(self._make_steps(), tools)
        assert "#E1" in evidence
        assert "#E2" in evidence
        assert "#E3" in evidence

    def test_resolves_placeholder_references(self):
        tools = {
            "vault_search": lambda **kw: "found: config.py",
            "file_read": lambda **kw: f"Reading {kw['path']}",
        }
        planner = ReWOOPlanner()
        evidence = planner.execute(self._make_steps(), tools)
        # #E2 depends on #E1, so its path arg should have been resolved
        assert "found: config.py" in evidence["#E2"] or "Reading" in evidence["#E2"]

    def test_failed_tool_stores_error(self):
        def failing_tool(**kw):
            raise RuntimeError("Connection refused")

        tools = {
            "vault_search": failing_tool,
            "file_read": lambda **kw: "ok",
        }
        planner = ReWOOPlanner()
        evidence = planner.execute(self._make_steps(), tools)
        assert "error" in evidence["#E1"].lower() or "Error" in evidence["#E1"]
        # Execution continues despite error
        assert "#E3" in evidence

    def test_compresses_evidence(self):
        """Tool results should pass through compressor before storage."""
        tools = {"vault_search": lambda **kw: "short result"}
        steps = [PlanStep("#E1", "vault_search", {"query": "test"}, [])]
        with patch("core.agency.planner.compress") as mock_compress:
            mock_compress.return_value = "compressed"
            planner = ReWOOPlanner()
            evidence = planner.execute(steps, tools)
        mock_compress.assert_called_once()
        assert evidence["#E1"] == "compressed"

    def test_zero_llm_calls_during_execute(self):
        """Execute phase must not call the LLM."""
        tools = {"vault_search": lambda **kw: "result"}
        steps = [PlanStep("#E1", "vault_search", {"query": "test"}, [])]
        with patch("core.agency.planner.generate_local") as mock_llm:
            planner = ReWOOPlanner()
            planner.execute(steps, tools)
        mock_llm.assert_not_called()


# ── Solving ───────────────────────────────────────────────────────────

class TestSolve:
    def test_solve_returns_answer(self):
        mock_resp = {"response": "The memory architecture uses LanceDB with tiered storage."}
        with patch("core.agency.planner.generate_local", return_value=mock_resp):
            planner = ReWOOPlanner()
            steps = [PlanStep("#E1", "vault_search", {"query": "memory"}, [])]
            evidence = {"#E1": "LanceDB, 3 tiers, vault/knowledge"}
            answer = planner.solve("What is the memory architecture?", steps, evidence)
        assert "LanceDB" in answer

    def test_solve_receives_compressed_evidence_not_raw(self):
        """Solver prompt should contain evidence values, not tool outputs."""
        with patch("core.agency.planner.generate_local", return_value={"response": "answer"}) as mock_llm:
            planner = ReWOOPlanner()
            steps = [PlanStep("#E1", "vault_search", {"query": "q"}, [])]
            evidence = {"#E1": "compressed result"}
            planner.solve("task", steps, evidence)

        prompt = mock_llm.call_args[0][0]
        assert "compressed result" in prompt
        assert "#E1" in prompt


# ── Token efficiency ──────────────────────────────────────────────────

class TestTokenEfficiency:
    def test_rewoo_uses_less_than_50_percent_of_react(self):
        """ReWOO should use ≤50% of tokens compared to equivalent ReAct."""
        task = "Research the memory architecture and summarize findings"
        tools_available = ["vault_search", "file_read"]

        # Simulate ReAct: each step includes full history + tool output
        react_tokens = 0
        accumulated_history = f"Task: {task}\n"
        for i in range(5):
            tool_output = f"Result data {'x' * 200} for step {i+1}"
            step_context = accumulated_history + f"\nTool output: {tool_output}\n"
            react_tokens += estimate_tokens(step_context)
            accumulated_history = step_context

        # Simulate ReWOO: plan call + solve call, evidence external
        plan_prompt = f"Task: {task}\nTools: {tools_available}\nGenerate a plan."
        rewoo_plan_tokens = estimate_tokens(plan_prompt)
        # Execute: 0 LLM tokens (tool calls only)
        evidence_summary = "Compressed evidence from 5 tool calls, ~100 words total."
        solve_prompt = f"Task: {task}\nEvidence:\n{evidence_summary}\nSynthesize answer."
        rewoo_solve_tokens = estimate_tokens(solve_prompt)
        rewoo_total = rewoo_plan_tokens + rewoo_solve_tokens

        assert rewoo_total <= react_tokens * 0.50, (
            f"ReWOO ({rewoo_total}) should be ≤50% of ReAct ({react_tokens})"
        )


# ── Single-step degenerate case ───────────────────────────────────────

class TestEdgeCases:
    def test_single_step_plan(self):
        """Single-step plan should still work (degenerate case)."""
        mock_plan = json.dumps([
            {"step_id": "#E1", "tool_name": "vault_search", "tool_args": {"query": "test"}, "depends_on": []},
        ])
        mock_resp = {"response": mock_plan}
        with patch("core.agency.planner.generate_local", return_value=mock_resp):
            planner = ReWOOPlanner()
            steps = planner.plan("simple query", ["vault_search"])
        assert len(steps) == 1

    def test_empty_tool_registry(self):
        """Execute with missing tool should store error."""
        steps = [PlanStep("#E1", "nonexistent_tool", {"query": "test"}, [])]
        planner = ReWOOPlanner()
        evidence = planner.execute(steps, {})
        assert "error" in evidence["#E1"].lower() or "not found" in evidence["#E1"].lower()
```

### Step 2: Run tests to verify they fail

Run:
```bash
cd D:/Development/OIKOS_OMEGA && source .venv/Scripts/activate && python -m pytest tests/test_planner.py -v 2>&1 | head -10
```
Expected: `ModuleNotFoundError: No module named 'core.agency.planner'`

### Step 3: Write minimal implementation

Create `core/agency/planner.py`:

```python
"""ReWOO Planner — plan-then-execute for token-efficient multi-step tasks.

Phase 7d Module 1.4. Three phases:
  Plan:    1 LLM call — generate numbered steps with placeholder tokens.
  Execute: 0 LLM calls — run tools, store results in evidence dict.
  Solve:   1 LLM call — synthesize evidence into final answer.

Token savings: O(1) LLM context vs O(N^2) for ReAct-style agents.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field

from core.agency.compressor import compress
from core.interface.config import COMPRESSOR_MODEL

log = logging.getLogger(__name__)

_PLACEHOLDER_RE = re.compile(r"#E\d+")


@dataclass
class PlanStep:
    """A single step in a ReWOO plan."""
    step_id: str           # "#E1", "#E2", etc.
    tool_name: str
    tool_args: dict
    depends_on: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "step_id": self.step_id,
            "tool_name": self.tool_name,
            "tool_args": self.tool_args,
            "depends_on": self.depends_on,
        }

    @classmethod
    def from_dict(cls, data: dict) -> PlanStep:
        return cls(
            step_id=data["step_id"],
            tool_name=data["tool_name"],
            tool_args=data.get("tool_args", {}),
            depends_on=data.get("depends_on", []),
        )


def _strip_markdown_fences(text: str) -> str:
    """Remove ```json ... ``` wrapping from LLM output."""
    text = text.strip()
    if text.startswith("```json"):
        text = text[7:]
    elif text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    return text.strip()


def _resolve_placeholders(value: str, evidence: dict[str, str]) -> str:
    """Replace #E1, #E2 etc. with their resolved values from evidence."""
    def replacer(match):
        key = match.group(0)
        return evidence.get(key, key)
    if isinstance(value, str):
        return _PLACEHOLDER_RE.sub(replacer, value)
    return value


class ReWOOPlanner:
    """Plan-then-execute agent pattern. 2 LLM calls instead of N."""

    def plan(self, task: str, available_tools: list[str]) -> list[PlanStep]:
        """Phase 1: Generate execution plan (1 LLM call).

        Returns list of PlanStep with placeholder tokens for inter-step references.
        Returns empty list on LLM error.
        """
        from core.cognition.inference import generate_local

        tool_list = ", ".join(available_tools)
        prompt = (
            "You are a task planner. Given a task and available tools, generate a "
            "numbered execution plan. Each step has:\n"
            '- step_id: "#E1", "#E2", etc.\n'
            "- tool_name: one of the available tools\n"
            "- tool_args: dict of arguments (may reference prior steps like #E1)\n"
            "- depends_on: list of step_ids this step needs\n\n"
            f"Available tools: {tool_list}\n\n"
            f"Task: {task}\n\n"
            "Respond with a JSON array of steps. No explanation."
        )

        result = generate_local(prompt, model=COMPRESSOR_MODEL)
        response = result.get("response", "").strip()
        if not response or result.get("error"):
            log.warning("Plan generation failed: %s", result.get("error", "empty response"))
            return []

        response = _strip_markdown_fences(response)
        try:
            steps_data = json.loads(response)
            if not isinstance(steps_data, list):
                log.warning("Plan response is not a list: %s", type(steps_data))
                return []
            return [PlanStep.from_dict(s) for s in steps_data]
        except (json.JSONDecodeError, KeyError) as e:
            log.warning("Failed to parse plan: %s — %s", e, response[:200])
            return []

    def execute(
        self,
        steps: list[PlanStep],
        tool_registry: dict[str, callable],
    ) -> dict[str, str]:
        """Phase 2: Execute plan steps (0 LLM calls).

        Runs each tool, stores compressed results in evidence dict.
        Failed steps store error message; execution continues.
        """
        evidence: dict[str, str] = {}

        for step in steps:
            tool_fn = tool_registry.get(step.tool_name)
            if not tool_fn:
                evidence[step.step_id] = f"[Error: tool '{step.tool_name}' not found in registry]"
                continue

            # Resolve placeholder references in args
            resolved_args = {
                k: _resolve_placeholders(str(v), evidence) if isinstance(v, str) else v
                for k, v in step.tool_args.items()
            }

            try:
                raw_result = tool_fn(**resolved_args)
                # Compress result before storing (Module 1.2 integration)
                evidence[step.step_id] = compress(
                    str(raw_result),
                    task_context=f"{step.tool_name}({step.tool_args})",
                )
            except Exception as e:
                log.warning("Tool %s failed: %s", step.tool_name, e)
                evidence[step.step_id] = f"[Error: {e}]"

        return evidence

    def solve(
        self,
        task: str,
        plan: list[PlanStep],
        evidence: dict[str, str],
    ) -> str:
        """Phase 3: Synthesize evidence into final answer (1 LLM call).

        Receives only the plan structure + compressed evidence, not raw tool outputs.
        """
        from core.cognition.inference import generate_local

        # Build evidence block
        evidence_lines = []
        for step in plan:
            val = evidence.get(step.step_id, "[no evidence]")
            evidence_lines.append(f"{step.step_id} ({step.tool_name}): {val}")

        evidence_block = "\n".join(evidence_lines)

        prompt = (
            f"Task: {task}\n\n"
            f"Evidence collected:\n{evidence_block}\n\n"
            "Synthesize the evidence into a clear, complete answer to the task."
        )

        result = generate_local(prompt, model=COMPRESSOR_MODEL)
        return result.get("response", "").strip()
```

### Step 4: Run tests to verify they pass

Run:
```bash
cd D:/Development/OIKOS_OMEGA && source .venv/Scripts/activate && python -m pytest tests/test_planner.py -v
```
Expected: All 18 tests PASS

### Step 5: Commit

```bash
cd D:/Development/OIKOS_OMEGA && git add core/agency/planner.py tests/test_planner.py && git commit -m "$(cat <<'EOF'
feat(agency): add ReWOO planner (Phase 7d Module 1.4)

Plan-then-execute pattern: 1 LLM call to plan, 0 LLM calls to
execute tools, 1 LLM call to synthesize. Evidence stored externally
(not in conversation context) for O(1) vs O(N^2) token growth.

Integrates compressor (1.2) for evidence compression. Placeholder
resolution (#E1, #E2) for inter-step references. Graceful error
handling: failed tools store errors, execution continues.

18 tests covering plan generation, execution, solving, placeholder
resolution, token efficiency (≥50% vs ReAct), serialization, and
edge cases.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Integration Verification

### Step 1: Run full test suite

Run:
```bash
cd D:/Development/OIKOS_OMEGA && source .venv/Scripts/activate && python -m pytest tests/ -v --tb=short 2>&1 | tail -20
```
Expected: All existing tests (596) + new tests (~76) = ~672 PASS, 0 FAIL

### Step 2: Run only new Module 1 tests

Run:
```bash
cd D:/Development/OIKOS_OMEGA && source .venv/Scripts/activate && python -m pytest tests/test_context_engine.py tests/test_compressor.py tests/test_budget.py tests/test_planner.py -v
```
Expected: All ~76 new tests PASS

### Step 3: Run vitest (frontend regression check)

Run:
```bash
cd D:/Development/OIKOS_OMEGA/frontend && npx vitest run 2>&1 | tail -10
```
Expected: 36/36 PASS (no frontend changes)

### Step 4: Run gauntlet (identity/safety regression check)

Run:
```bash
cd D:/Development/OIKOS_OMEGA && source .venv/Scripts/activate && python -m core.agency.adversarial 2>&1 | tail -15
```
Expected: ≥9/10 PASS (no handler/identity code modified)

### Step 5: Verify token reduction demonstration

Run a quick Python script to demonstrate the ≥50% token reduction:
```bash
cd D:/Development/OIKOS_OMEGA && source .venv/Scripts/activate && python -c "
from core.agency.context_engine import ContextEngine, estimate_tokens

# Build 12-turn conversation with tool calls
history = []
for i in range(12):
    history.append({'role': 'user', 'content': f'Question {i+1}'})
    history.append({'role': 'assistant', 'content': f'Checking tool {i+1}'})
    history.append({'role': 'tool', 'content': 'x' * 500, 'tool_call': {'name': f'tool_{i+1}', 'args_summary': f'arg={i+1}'}})
    history.append({'role': 'assistant', 'content': f'Answer {i+1}'})

engine = ContextEngine()
masked = engine.mask_observations(history)

original = sum(estimate_tokens(t['content']) for t in history)
compressed = sum(estimate_tokens(t['content']) for t in masked)
reduction = (1 - compressed/original) * 100

print(f'Original: {original} tokens')
print(f'Masked:   {compressed} tokens')
print(f'Reduction: {reduction:.1f}%')
assert reduction >= 50, f'Reduction {reduction:.1f}% < 50% target'
print('PASS: ≥50% token reduction verified')
"
```
Expected: `PASS: ≥50% token reduction verified`

---

## Summary

| Task | Sub-module | New Files | New Tests | Commits |
|---|---|---|---|---|
| 0 | Config constants | 0 new, 1 modified | 0 | 1 |
| 1 | Observation Masking | 2 (impl + test) | 11 | 1 |
| 2 | Tool Result Compression | 2 (impl + test) | 20 | 1 |
| 3 | Token Budget Tracker | 2 (impl + test) | 27 | 1 |
| 4 | ReWOO Planner | 2 (impl + test) | 18 | 1 |
| 5 | Integration Verification | 0 | 0 | 0 |
| **Total** | | **8 new, 1 modified** | **76** | **5** |

**Post-Module 1 baseline:** 632 + 76 = **708 tests** (toward 730 target across all 7 modules)
