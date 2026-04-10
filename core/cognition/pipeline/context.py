"""Context assembly — vault scoping, compilation, and prompt construction.

T-110: Enriched system prompt with Room personality and deferred tool listing.
"""

from __future__ import annotations

import logging
from typing import NamedTuple

from core.cognition.compiler import compile_context, render_context
from core.cognition.inference import load_system_prompt
from core.framework.tool_pool import assemble_tool_pool, render_deferred_listing
from core.interface.config import DEFAULT_TOKEN_BUDGET
from core.interface.models import CompiledContext
from core.interface.settings import get_setting
from core.memory.vault_index import truncate_vault_index

log = logging.getLogger(__name__)


class ContextResult(NamedTuple):
    compiled: CompiledContext
    context_block: str
    system_prompt: str | None
    full_prompt: str


def build_system_prompt(
    identity: str | None,
    personality: str | None = None,
    deferred_listing: str | None = None,
) -> str | None:
    """Assemble sectioned system prompt per SYNTH ruling (T-110).

    Section order: identity → personality → deferred tool listing.
    Personality is additive — never replaces identity.
    """
    sections = []
    if identity:
        sections.append(identity)
    if personality:
        sections.append(f"## Room Personality\n{personality}")
    if deferred_listing:
        sections.append(deferred_listing)
    return "\n\n".join(sections) if sections else None


def assemble_context(effective_query: str) -> ContextResult:
    """Stages 3-4: room vault scoping, context compilation, prompt assembly."""
    path_filter = None
    exclude_filter = None
    tag_filter = None
    personality = None
    allowed_toolsets = None
    vault_index_limit = None
    try:
        from core.rooms.manager import get_room_manager
        room = get_room_manager().get_active_room()
        if room.vault_scope.mode == "include" and room.vault_scope.paths:
            path_filter = room.vault_scope.paths
        elif room.vault_scope.mode == "exclude" and room.vault_scope.paths:
            exclude_filter = room.vault_scope.paths
        if room.vault_scope.tags:
            tag_filter = room.vault_scope.tags
        personality = room.voice.personality
        allowed_toolsets = room.toolsets
        vault_index_limit = room.limits.vault_index_limit
    except (ImportError, ValueError):
        pass

    try:
        compiled = compile_context(
            effective_query,
            token_budget=int(get_setting("default_token_budget")),
            path_filter=path_filter,
            exclude_filter=exclude_filter,
            tag_filter=tag_filter,
        )
        context_block = render_context(compiled)
    except (ValueError, RuntimeError, OSError) as e:
        log.warning("Context compilation failed: %s", e)
        context_block = "(no context available)"
        compiled = CompiledContext(
            query=effective_query, slices=[], total_tokens=0, budget=DEFAULT_TOKEN_BUDGET,
        )

    if vault_index_limit is not None:
        context_block = truncate_vault_index(context_block, max_entries=vault_index_limit)

    pool = assemble_tool_pool(allowed_toolsets)
    deferred_listing = render_deferred_listing(pool.deferred_tools) or None

    identity = load_system_prompt("sovereign")
    system_prompt = build_system_prompt(identity, personality, deferred_listing)

    full_prompt = f"{context_block}\n\n---\nQuery: {effective_query}"

    return ContextResult(compiled=compiled, context_block=context_block, system_prompt=system_prompt, full_prompt=full_prompt)
