from __future__ import annotations

import copy

import pytest

from core.agency.context_engine import ContextEngine, estimate_tokens


def _make_turn(role, content, tool_call=None):
    turn = {"role": role, "content": content}
    if tool_call:
        turn["tool_call"] = tool_call
    return turn


def _make_tool_turn(tool_name, args_summary, output):
    return {
        "role": "tool",
        "content": output,
        "tool_call": {"name": tool_name, "args_summary": args_summary},
    }


BIG_OUTPUT = "x " * 100  # 200 chars, 100 words -> ~130 tokens


class TestEstimateTokens:
    def test_empty_string(self):
        assert estimate_tokens("") == 0

    def test_single_word(self):
        assert estimate_tokens("hello") == int(1 * 1.3)

    def test_sentence(self):
        assert estimate_tokens("The quick brown fox jumps over the lazy dog") == int(9 * 1.3)


class TestContextEngineTiers:
    def test_hot_tier_preserved(self):
        """Last 3 tool calls in a 5-tool conversation have full outputs."""
        history = []
        for i in range(5):
            history.append(_make_turn("user", f"question {i}"))
            history.append(_make_tool_turn(f"tool_{i}", f"arg={i}", BIG_OUTPUT))

        result = ContextEngine().mask_observations(history)
        tool_turns = [t for t in result if t["role"] == "tool"]
        for t in tool_turns[-3:]:
            assert t["content"] == BIG_OUTPUT

    def test_warm_tier_masked(self):
        """Tool calls ranked 4-10 get warm placeholder."""
        history = []
        for i in range(10):
            history.append(_make_turn("user", f"q{i}"))
            history.append(_make_tool_turn(f"tool_{i}", f"a={i}", BIG_OUTPUT))

        result = ContextEngine().mask_observations(history)
        tool_turns = [t for t in result if t["role"] == "tool"]
        # Warm: indices 0-6 (ranks 10 down to 4)
        for t in tool_turns[:7]:
            assert t["content"].startswith("[masked")
            assert "tokens removed" in t["content"]

    def test_cold_tier_collapsed(self):
        """Tool calls ranked 11+ get cold single-line placeholder."""
        history = []
        for i in range(12):
            history.append(_make_turn("user", f"q{i}"))
            history.append(_make_tool_turn(f"tool_{i}", f"a={i}", BIG_OUTPUT))

        result = ContextEngine().mask_observations(history)
        tool_turns = [t for t in result if t["role"] == "tool"]
        # Cold: first 2 tools (ranks 12, 11)
        for t in tool_turns[:2]:
            assert t["content"].startswith("[Turn")
            assert "details masked" in t["content"]

    def test_no_tool_calls_passthrough(self):
        history = [
            _make_turn("user", "hello"),
            _make_turn("assistant", "hi there"),
        ]
        result = ContextEngine().mask_observations(history)
        assert result == history

    def test_single_tool_call_is_hot(self):
        history = [
            _make_turn("user", "q"),
            _make_tool_turn("read_file", "path=/tmp/x", BIG_OUTPUT),
        ]
        result = ContextEngine().mask_observations(history)
        assert result[1]["content"] == BIG_OUTPUT

    def test_exactly_three_all_hot(self):
        history = []
        for i in range(3):
            history.append(_make_turn("user", f"q{i}"))
            history.append(_make_tool_turn(f"t{i}", f"a={i}", BIG_OUTPUT))

        result = ContextEngine().mask_observations(history)
        for t in result:
            if t["role"] == "tool":
                assert t["content"] == BIG_OUTPUT

    def test_non_tool_turns_never_masked(self):
        history = []
        for i in range(12):
            history.append(_make_turn("user", f"long question {i} " * 20))
            history.append(_make_turn("assistant", f"long answer {i} " * 20))
            history.append(_make_tool_turn(f"t{i}", f"a={i}", BIG_OUTPUT))

        result = ContextEngine().mask_observations(history)
        for t in result:
            if t["role"] in ("user", "assistant"):
                assert "[masked" not in t["content"]
                assert "[Turn" not in t["content"]

    def test_token_reduction_40_percent(self):
        """Spec: masked output ≤40% of original for 10+ tool calls."""
        history = []
        for i in range(12):
            history.append(_make_turn("user", f"q{i}"))
            history.append(_make_tool_turn(f"t{i}", f"a={i}", BIG_OUTPUT))

        original_tokens = sum(estimate_tokens(t["content"]) for t in history)
        result = ContextEngine().mask_observations(history)
        masked_tokens = sum(estimate_tokens(t["content"]) for t in result)
        assert masked_tokens <= original_tokens * 0.4

    def test_custom_window_size(self):
        history = []
        for i in range(5):
            history.append(_make_turn("user", f"q{i}"))
            history.append(_make_tool_turn(f"t{i}", f"a={i}", BIG_OUTPUT))

        result = ContextEngine(hot_window=1).mask_observations(history)
        tool_turns = [t for t in result if t["role"] == "tool"]
        # Only last 1 should be hot
        assert tool_turns[-1]["content"] == BIG_OUTPUT
        assert tool_turns[-2]["content"].startswith("[masked")

    def test_warm_preserves_tool_metadata(self):
        history = [
            _make_turn("user", "q0"),
            _make_tool_turn("search_vault", "query=doctrine", BIG_OUTPUT),
        ]
        # Add 3 more to push the first into warm
        for i in range(3):
            history.append(_make_turn("user", f"q{i+1}"))
            history.append(_make_tool_turn(f"t{i}", f"a={i}", BIG_OUTPUT))

        result = ContextEngine().mask_observations(history)
        warm_turn = [t for t in result if t["role"] == "tool"][0]
        assert "search_vault" in warm_turn["content"]
        assert "query=doctrine" in warm_turn["content"]

    def test_does_not_mutate_input(self):
        history = [
            _make_turn("user", "q"),
            _make_tool_turn("t", "a=1", BIG_OUTPUT),
        ]
        original = copy.deepcopy(history)
        ContextEngine().mask_observations(history)
        assert history == original
