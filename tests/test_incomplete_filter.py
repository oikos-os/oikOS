"""Tests for T-109 Gate 1: incomplete tool call filtering."""

import pytest
from core.framework.filters import filter_incomplete_tool_calls


class TestIncompleteFilter:
    def test_empty_messages(self):
        assert filter_incomplete_tool_calls([]) == []

    def test_no_tool_calls_passthrough(self):
        msgs = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi there"},
        ]
        assert filter_incomplete_tool_calls(msgs) == msgs

    def test_complete_tool_call_preserved(self):
        msgs = [
            {"role": "user", "content": "do something"},
            {"role": "assistant", "content": [
                {"type": "text", "text": "I'll search"},
                {"type": "tool_use", "id": "tu_1", "name": "search", "input": {}},
            ]},
            {"role": "tool", "tool_use_id": "tu_1", "content": "results"},
        ]
        result = filter_incomplete_tool_calls(msgs)
        assert len(result) == 3

    def test_orphaned_tool_use_stripped(self):
        msgs = [
            {"role": "user", "content": "do something"},
            {"role": "assistant", "content": [
                {"type": "tool_use", "id": "tu_orphan", "name": "search", "input": {}},
            ]},
            {"role": "user", "content": "next message"},
        ]
        result = filter_incomplete_tool_calls(msgs)
        assert len(result) == 2
        assert result[0]["role"] == "user"
        assert result[1]["role"] == "user"

    def test_mixed_complete_and_orphaned(self):
        msgs = [
            {"role": "assistant", "content": [
                {"type": "tool_use", "id": "tu_ok", "name": "read", "input": {}},
            ]},
            {"role": "tool", "tool_use_id": "tu_ok", "content": "file content"},
            {"role": "assistant", "content": [
                {"type": "tool_use", "id": "tu_orphan", "name": "write", "input": {}},
            ]},
        ]
        result = filter_incomplete_tool_calls(msgs)
        assert len(result) == 2
        # The complete tool_use + result kept, orphaned stripped
        assert result[0]["role"] == "assistant"
        assert result[1]["role"] == "tool"

    def test_content_array_tool_results(self):
        """Tool results in content-array format (user role with tool_result blocks)."""
        msgs = [
            {"role": "assistant", "content": [
                {"type": "tool_use", "id": "tu_1", "name": "search", "input": {}},
            ]},
            {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "tu_1", "content": "ok"},
            ]},
        ]
        result = filter_incomplete_tool_calls(msgs)
        assert len(result) == 2

    def test_multiple_tool_uses_in_one_message(self):
        """Message with multiple tool_use blocks — if any is orphaned, strip the message."""
        msgs = [
            {"role": "assistant", "content": [
                {"type": "tool_use", "id": "tu_1", "name": "read", "input": {}},
                {"type": "tool_use", "id": "tu_2", "name": "search", "input": {}},
            ]},
            {"role": "tool", "tool_use_id": "tu_1", "content": "read result"},
            # tu_2 has no result — the assistant message should be stripped
        ]
        result = filter_incomplete_tool_calls(msgs)
        # Assistant message stripped because tu_2 is orphaned
        assert len(result) == 1
        assert result[0]["role"] == "tool"

    def test_no_orphans_is_noop(self):
        msgs = [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
        ]
        assert filter_incomplete_tool_calls(msgs) is msgs

    def test_empty_list_returns_empty(self):
        assert filter_incomplete_tool_calls([]) == []

    def test_matched_pairs_preserved(self):
        """Complete tool_use/tool_result pairs are never stripped."""
        msgs = [
            {"role": "assistant", "content": [
                {"type": "tool_use", "id": "tu_ok", "name": "read", "input": {}},
            ]},
            {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "tu_ok", "content": "data"},
            ]},
        ]
        result = filter_incomplete_tool_calls(msgs)
        assert len(result) == 2

    def test_orphaned_tool_use_stripped(self):
        """Orphaned tool_use blocks cause their assistant message to be removed."""
        msgs = [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": [
                {"type": "tool_use", "id": "tu_orphan", "name": "search", "input": {}},
            ]},
        ]
        result = filter_incomplete_tool_calls(msgs)
        assert len(result) == 1
        assert result[0]["role"] == "user"

    def test_mixed_orphaned_and_complete(self):
        """Only the orphaned assistant message is stripped; complete pairs remain."""
        msgs = [
            {"role": "assistant", "content": [
                {"type": "tool_use", "id": "tu_good", "name": "read", "input": {}},
            ]},
            {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "tu_good", "content": "ok"},
            ]},
            {"role": "assistant", "content": [
                {"type": "tool_use", "id": "tu_bad", "name": "write", "input": {}},
            ]},
        ]
        result = filter_incomplete_tool_calls(msgs)
        assert len(result) == 2
        assert all(r["role"] != "assistant" or "tu_good" in str(r) for r in result)
