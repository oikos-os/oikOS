"""Vault index truncation — caps vault index size for context window management.

T-109 Gate 3 (R5): Prevents vault index from consuming excessive context window
space. Configurable per-Room via vault_index_limit.
"""

from __future__ import annotations

MAX_VAULT_INDEX_ENTRIES = 200
MAX_VAULT_INDEX_BYTES = 25_000  # ~25KB


def truncate_vault_index(
    index: str,
    max_entries: int = MAX_VAULT_INDEX_ENTRIES,
    max_bytes: int = MAX_VAULT_INDEX_BYTES,
) -> str:
    """Truncate vault index to prevent context window consumption.

    Args:
        index: Raw vault index string (newline-separated entries).
        max_entries: Maximum number of entries (configurable per Room).
        max_bytes: Maximum byte size.

    Returns:
        Truncated index with warning appended if truncation occurred.
    """
    if not index or not index.strip():
        return index

    lines = index.strip().split("\n")
    total_line_count = len(lines)

    if total_line_count > max_entries:
        lines = lines[:max_entries]

    result = "\n".join(lines)

    if len(result.encode("utf-8")) > max_bytes:
        # UTF-8 characters span multiple bytes — binary search finds the
        # largest line count whose join fits within the byte budget.
        lo, hi = 0, len(lines) - 1
        while lo < hi:
            mid = (lo + hi + 1) // 2
            candidate = "\n".join(lines[:mid])
            if len(candidate.encode("utf-8")) <= max_bytes:
                lo = mid
            else:
                hi = mid - 1
        result = "\n".join(lines[:lo])
        result += "\n[... truncated to fit context budget — use vault_search for full access]"
    elif len(lines) < total_line_count:
        remaining = total_line_count - len(lines)
        result += (
            f"\n[... {remaining} more entries"
            " — use vault_search to find specific documents]"
        )

    return result
