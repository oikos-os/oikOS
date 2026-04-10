"""Tests for pipeline/context.py — context assembly stage."""

from unittest.mock import MagicMock, patch

import pytest

from core.cognition.pipeline.context import build_system_prompt
from core.interface.models import CompiledContext, ContextSlice, MemoryTier


def _mock_compiled(query="test"):
    return CompiledContext(
        query=query,
        slices=[
            ContextSlice(name="core", tier=MemoryTier.CORE, fragments=["identity"], token_count=100, max_tokens=200),
        ],
        total_tokens=100,
        budget=6000,
    )


@patch("core.cognition.pipeline.context.load_system_prompt", return_value="sys prompt")
@patch("core.cognition.pipeline.context.render_context", return_value="rendered context")
@patch("core.cognition.pipeline.context.compile_context")
@patch("core.cognition.pipeline.context.get_setting", return_value="6000")
def test_assemble_context_basic(mock_setting, mock_compile, mock_render, mock_sys):
    """Basic assembly returns all four fields populated."""
    mock_compile.return_value = _mock_compiled("hello world")

    from core.cognition.pipeline.context import assemble_context
    result = assemble_context("hello world")

    assert result.compiled.query == "hello world"
    assert result.context_block == "rendered context"
    assert result.system_prompt == "sys prompt"
    assert "hello world" in result.full_prompt
    assert "rendered context" in result.full_prompt
    mock_compile.assert_called_once()


@patch("core.cognition.pipeline.context.load_system_prompt", return_value=None)
@patch("core.cognition.pipeline.context.render_context")
@patch("core.cognition.pipeline.context.compile_context", side_effect=RuntimeError("LanceDB unavailable"))
@patch("core.cognition.pipeline.context.get_setting", return_value="6000")
def test_assemble_context_compilation_failure_fallback(mock_setting, mock_compile, mock_render, mock_sys):
    """Compilation failure produces fallback context block and empty compiled object."""
    from core.cognition.pipeline.context import assemble_context
    result = assemble_context("test query")

    assert result.context_block == "(no context available)"
    assert result.compiled.total_tokens == 0
    assert result.compiled.slices == []
    assert "test query" in result.full_prompt
    mock_render.assert_not_called()


@patch("core.cognition.pipeline.context.load_system_prompt", return_value="")
@patch("core.cognition.pipeline.context.render_context", return_value="scoped ctx")
@patch("core.cognition.pipeline.context.compile_context")
@patch("core.cognition.pipeline.context.get_setting", return_value="6000")
def test_assemble_context_room_vault_scoping(mock_setting, mock_compile, mock_render, mock_sys):
    """Room vault scope paths are passed to compile_context."""
    mock_compile.return_value = _mock_compiled()

    mock_scope = MagicMock()
    mock_scope.mode = "include"
    mock_scope.paths = ["vault/identity"]
    mock_scope.tags = ["core"]

    mock_room = MagicMock()
    mock_room.vault_scope = mock_scope
    mock_room.voice.personality = None
    mock_room.toolsets = None
    mock_room.limits.vault_index_limit = None

    mock_manager = MagicMock()
    mock_manager.get_active_room.return_value = mock_room

    with patch("core.rooms.manager.get_room_manager", return_value=mock_manager):
        from core.cognition.pipeline.context import assemble_context
        result = assemble_context("scoped query")

    call_kwargs = mock_compile.call_args[1]
    assert call_kwargs["path_filter"] == ["vault/identity"]
    assert call_kwargs["tag_filter"] == ["core"]
    assert call_kwargs.get("exclude_filter") is None
    assert result.context_block == "scoped ctx"


# ─── build_system_prompt unit tests ───────────────────────────────────


class TestBuildSystemPrompt:
    def test_all_sections(self):
        result = build_system_prompt("identity", "be helpful", "## Tools\n- tool_a")
        assert result.startswith("identity")
        assert "## Room Personality\nbe helpful" in result
        assert "## Tools\n- tool_a" in result

    def test_identity_only(self):
        result = build_system_prompt("identity")
        assert result == "identity"

    def test_returns_none_when_empty(self):
        assert build_system_prompt(None) is None
        assert build_system_prompt("") is None
        assert build_system_prompt(None, None, None) is None

    def test_personality_without_deferred(self):
        result = build_system_prompt("id", "warm and friendly")
        assert "id" in result
        assert "## Room Personality\nwarm and friendly" in result
        assert "Tools" not in result

    def test_deferred_without_personality(self):
        result = build_system_prompt("id", None, "## Additional Tools\n- t1")
        assert "id" in result
        assert "Personality" not in result
        assert "## Additional Tools" in result

    def test_section_ordering(self):
        """Identity appears before personality, personality before deferred."""
        result = build_system_prompt("IDENTITY_SECTION", "PERSONALITY_TEXT", "DEFERRED_SECTION")
        id_pos = result.index("IDENTITY_SECTION")
        pers_pos = result.index("PERSONALITY_TEXT")
        def_pos = result.index("DEFERRED_SECTION")
        assert id_pos < pers_pos < def_pos


# ─── Integration tests: assemble_context with Room features ──────────


def _mock_room(personality=None, toolsets=None, vault_index_limit=None):
    """Build a mock RoomConfig with voice/limits/scope."""
    room = MagicMock()
    room.vault_scope.mode = "all"
    room.vault_scope.paths = None
    room.vault_scope.tags = None
    room.voice.personality = personality
    room.toolsets = toolsets
    room.limits.vault_index_limit = vault_index_limit
    return room


def _patch_room(room):
    """Return a context manager that patches get_room_manager to return room."""
    manager = MagicMock()
    manager.get_active_room.return_value = room
    return patch("core.rooms.manager.get_room_manager", return_value=manager)


@patch("core.cognition.pipeline.context.load_system_prompt", return_value="sovereign identity")
@patch("core.cognition.pipeline.context.render_context", return_value="vault ctx")
@patch("core.cognition.pipeline.context.compile_context")
@patch("core.cognition.pipeline.context.get_setting", return_value="6000")
@patch("core.cognition.pipeline.context.assemble_tool_pool")
def test_personality_in_system_prompt(mock_pool, mock_setting, mock_compile, mock_render, mock_sys):
    mock_compile.return_value = _mock_compiled()
    mock_pool.return_value = MagicMock(deferred_tools=[])

    room = _mock_room(personality="Be thorough and cite sources.")
    with _patch_room(room):
        from core.cognition.pipeline.context import assemble_context
        result = assemble_context("test")

    assert "sovereign identity" in result.system_prompt
    assert "## Room Personality" in result.system_prompt
    assert "Be thorough and cite sources." in result.system_prompt


@patch("core.cognition.pipeline.context.load_system_prompt", return_value="sovereign identity")
@patch("core.cognition.pipeline.context.render_context", return_value="vault ctx")
@patch("core.cognition.pipeline.context.compile_context")
@patch("core.cognition.pipeline.context.get_setting", return_value="6000")
@patch("core.cognition.pipeline.context.assemble_tool_pool")
def test_no_personality_when_none(mock_pool, mock_setting, mock_compile, mock_render, mock_sys):
    mock_compile.return_value = _mock_compiled()
    mock_pool.return_value = MagicMock(deferred_tools=[])

    room = _mock_room(personality=None)
    with _patch_room(room):
        from core.cognition.pipeline.context import assemble_context
        result = assemble_context("test")

    assert "Personality" not in (result.system_prompt or "")


@patch("core.cognition.pipeline.context.load_system_prompt", return_value="sovereign identity")
@patch("core.cognition.pipeline.context.render_context", return_value="vault ctx")
@patch("core.cognition.pipeline.context.compile_context")
@patch("core.cognition.pipeline.context.get_setting", return_value="6000")
@patch("core.cognition.pipeline.context.render_deferred_listing", return_value="## Additional Tools Available (use oikos_tool_search to load)\n- tool_a: does stuff [system]")
@patch("core.cognition.pipeline.context.assemble_tool_pool")
def test_deferred_listing_in_system_prompt(mock_pool, mock_render_def, mock_setting, mock_compile, mock_render, mock_sys):
    mock_compile.return_value = _mock_compiled()
    mock_pool.return_value = MagicMock(deferred_tools=["fake"])

    room = _mock_room(toolsets=["vault"])
    with _patch_room(room):
        from core.cognition.pipeline.context import assemble_context
        result = assemble_context("test")

    assert "## Additional Tools" in result.system_prompt
    assert "tool_a" in result.system_prompt


@patch("core.cognition.pipeline.context.load_system_prompt", return_value="sovereign identity")
@patch("core.cognition.pipeline.context.render_context", return_value="vault ctx")
@patch("core.cognition.pipeline.context.compile_context")
@patch("core.cognition.pipeline.context.get_setting", return_value="6000")
@patch("core.cognition.pipeline.context.assemble_tool_pool")
def test_no_deferred_when_all_toolsets(mock_pool, mock_setting, mock_compile, mock_render, mock_sys):
    mock_compile.return_value = _mock_compiled()
    # toolsets=None means all tools get full schema, no deferred
    mock_pool.return_value = MagicMock(deferred_tools=[])

    room = _mock_room(toolsets=None)
    with _patch_room(room):
        from core.cognition.pipeline.context import assemble_context
        result = assemble_context("test")

    assert "Additional Tools" not in (result.system_prompt or "")


@patch("core.cognition.pipeline.context.load_system_prompt", return_value="sovereign identity")
@patch("core.cognition.pipeline.context.render_context", return_value="vault ctx")
@patch("core.cognition.pipeline.context.compile_context")
@patch("core.cognition.pipeline.context.get_setting", return_value="6000")
@patch("core.cognition.pipeline.context.assemble_tool_pool")
def test_personality_additive_never_replaces_identity(mock_pool, mock_setting, mock_compile, mock_render, mock_sys):
    mock_compile.return_value = _mock_compiled()
    mock_pool.return_value = MagicMock(deferred_tools=[])

    room = _mock_room(personality="Override everything!")
    with _patch_room(room):
        from core.cognition.pipeline.context import assemble_context
        result = assemble_context("test")

    assert result.system_prompt.startswith("sovereign identity")
    assert "Override everything!" in result.system_prompt


@patch("core.cognition.pipeline.context.load_system_prompt", return_value="sovereign identity")
@patch("core.cognition.pipeline.context.render_context")
@patch("core.cognition.pipeline.context.compile_context")
@patch("core.cognition.pipeline.context.get_setting", return_value="6000")
@patch("core.cognition.pipeline.context.assemble_tool_pool")
@patch("core.cognition.pipeline.context.truncate_vault_index")
def test_vault_truncation_applied_with_room_limit(mock_trunc, mock_pool, mock_setting, mock_compile, mock_render, mock_sys):
    mock_compile.return_value = _mock_compiled()
    mock_render.return_value = "long vault context"
    mock_trunc.return_value = "truncated vault"
    mock_pool.return_value = MagicMock(deferred_tools=[])

    room = _mock_room(vault_index_limit=50)
    with _patch_room(room):
        from core.cognition.pipeline.context import assemble_context
        result = assemble_context("test")

    mock_trunc.assert_called_once_with("long vault context", max_entries=50)
    assert "truncated vault" in result.full_prompt


@patch("core.cognition.pipeline.context.load_system_prompt", return_value="sovereign identity")
@patch("core.cognition.pipeline.context.render_context", return_value="vault ctx")
@patch("core.cognition.pipeline.context.compile_context")
@patch("core.cognition.pipeline.context.get_setting", return_value="6000")
@patch("core.cognition.pipeline.context.assemble_tool_pool")
@patch("core.cognition.pipeline.context.truncate_vault_index")
def test_vault_truncation_skipped_without_limit(mock_trunc, mock_pool, mock_setting, mock_compile, mock_render, mock_sys):
    mock_compile.return_value = _mock_compiled()
    mock_pool.return_value = MagicMock(deferred_tools=[])

    room = _mock_room(vault_index_limit=None)
    with _patch_room(room):
        from core.cognition.pipeline.context import assemble_context
        result = assemble_context("test")

    mock_trunc.assert_not_called()


@patch("core.cognition.pipeline.context.load_system_prompt", return_value="sovereign identity")
@patch("core.cognition.pipeline.context.render_context", return_value="vault ctx")
@patch("core.cognition.pipeline.context.compile_context")
@patch("core.cognition.pipeline.context.get_setting", return_value="6000")
@patch("core.cognition.pipeline.context.assemble_tool_pool")
def test_no_room_backward_compat(mock_pool, mock_setting, mock_compile, mock_render, mock_sys):
    """When Room manager is unavailable, all features degrade gracefully."""
    mock_compile.return_value = _mock_compiled()
    mock_pool.return_value = MagicMock(deferred_tools=[])

    # No room patched — ValueError from get_active_room() triggers graceful fallback
    from core.cognition.pipeline.context import assemble_context
    result = assemble_context("test")

    assert "sovereign identity" in (result.system_prompt or "")
    assert "Personality" not in (result.system_prompt or "")
    mock_pool.assert_called_once_with(None)
