"""Tests for T-109 Gate 3: vault index truncation."""

import pytest
from core.memory.vault_index import (
    truncate_vault_index,
    MAX_VAULT_INDEX_ENTRIES,
    MAX_VAULT_INDEX_BYTES,
)


class TestVaultIndexTruncation:
    def test_empty_index(self):
        assert truncate_vault_index("") == ""
        assert truncate_vault_index("  ") == "  "

    def test_small_index_unchanged(self):
        index = "\n".join(f"entry_{i}" for i in range(10))
        result = truncate_vault_index(index)
        assert result == index

    def test_default_cap_200(self):
        index = "\n".join(f"entry_{i}" for i in range(300))
        result = truncate_vault_index(index)
        lines = result.strip().split("\n")
        # 200 entries + 1 truncation message
        assert len(lines) == 201
        assert "100 more entries" in lines[-1]

    def test_custom_cap(self):
        index = "\n".join(f"entry_{i}" for i in range(100))
        result = truncate_vault_index(index, max_entries=50)
        lines = result.strip().split("\n")
        assert len(lines) == 51
        assert "50 more entries" in lines[-1]

    def test_vault_search_hint_in_message(self):
        index = "\n".join(f"entry_{i}" for i in range(300))
        result = truncate_vault_index(index)
        assert "vault_search" in result

    def test_byte_truncation(self):
        # Create entries that exceed byte limit
        big_entry = "x" * 1000
        index = "\n".join(big_entry for _ in range(50))
        result = truncate_vault_index(index, max_bytes=5000)
        assert len(result.encode("utf-8")) <= 5000 + 200  # some slack for truncation message

    def test_byte_truncation_message(self):
        big_entry = "x" * 1000
        index = "\n".join(big_entry for _ in range(50))
        result = truncate_vault_index(index, max_bytes=5000)
        assert "truncated to fit context budget" in result

    def test_entry_truncation_before_byte(self):
        """When entry count is the binding constraint, not bytes."""
        index = "\n".join(f"e{i}" for i in range(300))
        result = truncate_vault_index(index, max_entries=50, max_bytes=100_000)
        lines = result.strip().split("\n")
        assert len(lines) == 51

    def test_constants(self):
        assert MAX_VAULT_INDEX_ENTRIES == 200
        assert MAX_VAULT_INDEX_BYTES == 25_000

    def test_unicode_safe(self):
        index = "\n".join(f"entry_{i}_\u00e9\u00e8\u00ea" for i in range(300))
        result = truncate_vault_index(index)
        # Should not crash on multi-byte characters
        assert "more entries" in result

    def test_room_limit_applied(self):
        """vault_index_limit=50 truncates a 100-entry index."""
        index = "\n".join(f"entry_{i}" for i in range(100))
        result = truncate_vault_index(index, max_entries=50)
        lines = result.strip().split("\n")
        assert len(lines) == 51  # 50 entries + 1 warning

    def test_none_limit_uses_default(self):
        """Default max_entries is MAX_VAULT_INDEX_ENTRIES (200)."""
        index = "\n".join(f"e{i}" for i in range(250))
        result = truncate_vault_index(index)
        lines = result.strip().split("\n")
        assert len(lines) == 201  # 200 + warning

    def test_truncation_on_rendered_context_format(self):
        """Truncation works on vault context with === TIER === headers."""
        entries = ["=== CORE (100 tokens) ==="] + [f"fragment_{i}" for i in range(300)]
        index = "\n".join(entries)
        result = truncate_vault_index(index, max_entries=50)
        lines = result.strip().split("\n")
        assert len(lines) == 51
        assert lines[0] == "=== CORE (100 tokens) ==="
