"""Message filters for the oikOS framework.

T-109 Gate 1 (R6): Incomplete tool call filtering — strips messages with
orphaned tool_use blocks (no matching tool_result) to prevent 400 errors
from interrupted sessions.
"""

from __future__ import annotations


def filter_incomplete_tool_calls(messages: list[dict]) -> list[dict]:
    """Strip messages with orphaned tool_use blocks (no matching tool_result).

    Prevents 400 errors from interrupted sessions where tool_use blocks
    were emitted but tool_result blocks were never sent.
    """
    if not messages:
        return messages

    tool_use_ids: set[str] = set()
    tool_result_ids: set[str] = set()

    for msg in messages:
        role = msg.get("role")
        if role == "assistant":
            for block in msg.get("content", []):
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    tid = block.get("id")
                    if tid:
                        tool_use_ids.add(tid)
        elif role == "tool":
            # Legacy format: tool_use_id on the message itself
            tid = msg.get("tool_use_id")
            if tid:
                tool_result_ids.add(tid)
        # Anthropic Messages API format: content-array with tool_result blocks
        if role == "user":
            for block in msg.get("content", []):
                if isinstance(block, dict) and block.get("type") == "tool_result":
                    tid = block.get("tool_use_id")
                    if tid:
                        tool_result_ids.add(tid)

    orphaned = tool_use_ids - tool_result_ids
    if not orphaned:
        return messages

    def _contains_orphaned(msg: dict) -> bool:
        if msg.get("role") != "assistant":
            return False
        for block in msg.get("content", []):
            if isinstance(block, dict) and block.get("type") == "tool_use":
                if block.get("id") in orphaned:
                    return True
        return False

    return [msg for msg in messages if not _contains_orphaned(msg)]
