"""Context Compiler v2 — token-budgeted context window assembly with identity hierarchy.

Phase 7a Module 1: Identity tier gets a fixed non-competitive allocation loaded first.
Assembly order: IDENTITY → CORE → SEMANTIC → PROCEDURAL → EPISODIC.
"""

from __future__ import annotations

import logging
import re

import tiktoken

from core.interface.config import (
    DEFAULT_TOKEN_BUDGET,
    IDENTITY_BUDGET_PCT,
    IDENTITY_FALLBACK_STRING,
    IDENTITY_TELOS_LIMIT,
    SLICE_ALLOCATIONS,
    VAULT_DIR,
)
from core.interface.models import CompiledContext, ContextSlice, FragmentMeta, MemoryTier
from core.memory.search import search_tier

log = logging.getLogger(__name__)

_enc = tiktoken.get_encoding("cl100k_base")

# Words extracted from semantic fragments that signal specific-topic coverage.
# Used by cross-tier dedup to detect when a broad core chunk overlaps.
_ENTITY_RE = re.compile(r"[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*")

# Path to the sovereign system prompt — always loaded in identity tier
_SYSTEM_MD = VAULT_DIR / "patterns" / "sovereign" / "system.md"


def count_tokens(text: str) -> int:
    """Count tokens using cl100k_base (overestimates ~5-10% for Llama, safe direction)."""
    return len(_enc.encode(text))


def _load_fallback(ctx_slice: ContextSlice) -> None:
    """Load hardcoded fallback identity string into an identity slice."""
    ctx_slice.fragments.append(IDENTITY_FALLBACK_STRING)
    ctx_slice.fragment_meta.append(
        FragmentMeta(source_path="[FALLBACK]", header_path="IDENTITY > Fallback")
    )
    ctx_slice.token_count = count_tokens(IDENTITY_FALLBACK_STRING)


def fill_identity_slice(query: str, budget: int) -> tuple[ContextSlice, set[str]]:
    """Fill the identity tier slice — non-competitive, always present.

    Step 1: Load vault/patterns/sovereign/system.md in full.
            Falls back to hardcoded identity string if file is missing or unreadable.
    Step 2: Fill remaining budget with top TELOS anchors by query relevance.

    Returns:
        (slice, telos_chunk_ids) where telos_chunk_ids is the set of chunk IDs
        loaded from CORE tier. The caller should exclude these from the core slice
        to prevent content duplication.
    """
    ctx_slice = ContextSlice(name="identity", tier=MemoryTier.CORE, max_tokens=budget)
    telos_ids: set[str] = set()

    # Step 1: Sovereign system prompt — always loaded, full file
    if _SYSTEM_MD.exists():
        try:
            content = _SYSTEM_MD.read_text(encoding="utf-8", errors="replace")
            tokens = count_tokens(content)
            ctx_slice.fragments.append(content)
            ctx_slice.fragment_meta.append(
                FragmentMeta(
                    source_path="vault/patterns/sovereign/system.md",
                    header_path="IDENTITY > Sovereign System Prompt",
                )
            )
            ctx_slice.token_count += tokens
            if tokens > budget:
                log.warning(
                    "[IDENTITY] system.md exceeds identity budget (%d > %d tokens) — "
                    "included anyway; identity is non-negotiable",
                    tokens,
                    budget,
                )
        except Exception as exc:
            log.warning("[IDENTITY] Failed to read system.md: %s — using fallback", exc)
            _load_fallback(ctx_slice)
    else:
        log.warning(
            "[IDENTITY] vault/patterns/sovereign/system.md missing — "
            "using fallback identity string"
        )
        _load_fallback(ctx_slice)

    # Step 2: TELOS anchors — fill remaining budget, query-dependent
    remaining = budget - ctx_slice.token_count
    if remaining > 0:
        telos_results = search_tier(query, MemoryTier.CORE, limit=IDENTITY_TELOS_LIMIT)
        for result in telos_results[:IDENTITY_TELOS_LIMIT]:
            frag_tokens = count_tokens(result.content)
            if ctx_slice.token_count + frag_tokens > budget:
                continue
            ctx_slice.fragments.append(result.content)
            ctx_slice.fragment_meta.append(
                FragmentMeta(
                    source_path=result.source_path,
                    header_path=result.header_path,
                )
            )
            ctx_slice.token_count += frag_tokens
            telos_ids.add(result.chunk_id)

    return ctx_slice, telos_ids


def fill_slice(
    query: str,
    tier: MemoryTier,
    slice_name: str,
    max_tokens: int,
    exclude_chunk_ids: set[str] | None = None,
) -> ContextSlice:
    """Search a tier and fill a slice with fragments until budget exhausted.

    No mid-fragment truncation — skip entire fragment if over budget.
    exclude_chunk_ids: skip chunks already loaded in the identity slice.
    """
    results = search_tier(query, tier, limit=20)
    ctx_slice = ContextSlice(name=slice_name, tier=tier, max_tokens=max_tokens)

    for result in results:
        if exclude_chunk_ids and result.chunk_id in exclude_chunk_ids:
            continue  # already in identity tier — skip to avoid duplication
        frag_tokens = count_tokens(result.content)
        if ctx_slice.token_count + frag_tokens > max_tokens:
            continue  # skip, don't truncate
        ctx_slice.fragments.append(result.content)
        ctx_slice.fragment_meta.append(
            FragmentMeta(source_path=result.source_path, header_path=result.header_path)
        )
        ctx_slice.token_count += frag_tokens

    return ctx_slice


def _extract_topic_keys(header_path: str, content: str) -> set[str]:
    """Extract lowercase topic identifiers from a semantic fragment.

    Pulls from the header path (e.g. "PROJECT: PROBLEM (RULEZ)") and
    capitalized multi-word entities in the first 200 chars of content.
    """
    keys: set[str] = set()
    # Header tokens (split on >, colons, parens, whitespace)
    for token in re.split(r"[>:()\s/]+", header_path):
        t = token.strip().lower()
        if len(t) >= 3:
            keys.add(t)
    # Capitalized entities from content lead
    for m in _ENTITY_RE.finditer(content[:200]):
        keys.add(m.group().lower())
    return keys


def _dedup_cross_tier(slices: list[ContextSlice]) -> list[ContextSlice]:
    """Remove broad core fragments that overlap with specific semantic fragments.

    When the semantic tier returns specific chunks (e.g. PROJECT: PROBLEM and
    PROJECT: SECRETS from MUSIC_RELEASES.md) and the core tier contains a broader
    chunk (e.g. a timeline table in GOALS.md listing all projects), the core chunk
    causes context bleed by presenting multiple project details side-by-side.

    Detection: group semantic chunks by source file. Extract distinctive topic keys
    per chunk. If a core fragment matches keys from 2+ chunks OF THE SAME semantic
    source file, it's a broad summary competing with specific knowledge — remove it.

    This prevents false positives from identity docs that incidentally mention
    project names in philosophical/strategic contexts.
    """
    core_slice = None
    semantic_slice = None
    for s in slices:
        if s.name == "core":
            core_slice = s
        elif s.name == "semantic":
            semantic_slice = s

    if not core_slice or not semantic_slice:
        return slices
    if not semantic_slice.fragments:
        return slices

    # Group semantic chunks by source file, extracting topic keys per chunk
    # Structure: {source_path: [(header_path, keys), ...]}
    chunks_by_file: dict[str, list[tuple[str, set[str]]]] = {}
    for i, frag in enumerate(semantic_slice.fragments):
        meta = semantic_slice.fragment_meta[i]
        keys = _extract_topic_keys(meta.header_path, frag)
        # Only keep keys with 4+ chars to avoid noise
        keys = {k for k in keys if len(k) >= 4}
        if keys:
            chunks_by_file.setdefault(meta.source_path, []).append((meta.header_path, keys))

    # Only consider files with 2+ chunks (multi-section knowledge files)
    multi_chunk_files = {f: chunks for f, chunks in chunks_by_file.items() if len(chunks) >= 2}
    if not multi_chunk_files:
        return slices

    # For each multi-chunk file, compute distinctive keys per chunk
    # (keys unique to that chunk within the file, not shared across all chunks of the file)
    file_distinctive: dict[str, list[tuple[str, set[str]]]] = {}
    for source_path, chunk_list in multi_chunk_files.items():
        # Count key frequency within this file's chunks
        file_key_freq: dict[str, int] = {}
        for _, keys in chunk_list:
            for k in keys:
                file_key_freq[k] = file_key_freq.get(k, 0) + 1
        # Keep only keys that appear in <=50% of this file's chunks
        max_freq = max(1, len(chunk_list) // 2)
        distinctive_chunks = []
        for header, keys in chunk_list:
            distinctive = {k for k in keys if file_key_freq.get(k, 0) <= max_freq}
            if distinctive:
                distinctive_chunks.append((header, distinctive))
        if len(distinctive_chunks) >= 2:
            file_distinctive[source_path] = distinctive_chunks

    if not file_distinctive:
        return slices

    # Check each core fragment for broad overlap with a SINGLE semantic file
    remove_indices: list[int] = []
    for i, frag in enumerate(core_slice.fragments):
        frag_lower = frag.lower()
        for source_path, distinctive_chunks in file_distinctive.items():
            # Count how many chunks from this file have distinctive keys in the core frag
            chunks_hit = 0
            for header, keys in distinctive_chunks:
                if any(k in frag_lower for k in keys):
                    chunks_hit += 1
            if chunks_hit >= 2:
                log.info(
                    "Cross-tier dedup: removing broad core fragment [%s] "
                    "(overlaps %d chunks from %s)",
                    core_slice.fragment_meta[i].header_path,
                    chunks_hit,
                    source_path,
                )
                remove_indices.append(i)
                break  # one match is enough to remove

    if not remove_indices:
        return slices

    # Rebuild core slice without overlapping fragments
    new_fragments = []
    new_meta = []
    new_token_count = 0
    for i, frag in enumerate(core_slice.fragments):
        if i in remove_indices:
            continue
        new_fragments.append(frag)
        new_meta.append(core_slice.fragment_meta[i])
        new_token_count += count_tokens(frag)

    core_slice.fragments = new_fragments
    core_slice.fragment_meta = new_meta
    core_slice.token_count = new_token_count

    return slices


def compile_context(
    query: str,
    token_budget: int = DEFAULT_TOKEN_BUDGET,
) -> CompiledContext:
    """Compile a full context window from all memory tiers.

    Assembly order (Phase 7a Module 1):
      [1] IDENTITY TIER — non-competitive, fixed budget, always present
          → vault/patterns/sovereign/system.md (full)
          → Top TELOS anchors (up to IDENTITY_TELOS_LIMIT, by relevance)
      [2] CORE, SEMANTIC, PROCEDURAL, EPISODIC — competitive, share remaining budget
          CORE tier excludes chunks already in identity to prevent duplication.

    Surplus from underspent slices is redistributed proportionally.
    Cross-tier dedup removes broad core fragments that overlap specific semantic hits.
    """
    tier_map = {
        "core": MemoryTier.CORE,
        "semantic": MemoryTier.SEMANTIC,
        "procedural": MemoryTier.PROCEDURAL,
        "episodic": MemoryTier.EPISODIC,
    }

    # Phase 1: Identity tier — fixed, non-competitive, always first
    identity_budget = int(IDENTITY_BUDGET_PCT * token_budget)
    identity_slice, telos_ids = fill_identity_slice(query, identity_budget)

    # Phase 2: Remaining budget for competitive tiers
    remaining_budget = token_budget - identity_budget
    allocations = {name: int(pct * remaining_budget) for name, pct in SLICE_ALLOCATIONS.items()}

    slices: list[ContextSlice] = [identity_slice]
    surplus = 0

    for name, tier in tier_map.items():
        budget = allocations[name]
        # Core tier: exclude TELOS chunks already included in identity slice
        exclude = telos_ids if name == "core" else None
        s = fill_slice(query, tier, name, budget, exclude_chunk_ids=exclude)
        surplus += budget - s.token_count
        slices.append(s)

    # Phase 3: Redistribute surplus to underfilled slices (identity excluded)
    if surplus > 0:
        underfilled = [
            s for s in slices
            if s.name != "identity" and s.token_count < s.max_tokens
        ]
        if underfilled:
            extra_per = surplus // len(underfilled)
            for s in underfilled:
                bonus = min(extra_per, surplus)
                if bonus <= 0:
                    break
                exclude = telos_ids if s.name == "core" else None
                expanded = fill_slice(
                    query, s.tier, s.name, s.max_tokens + bonus,
                    exclude_chunk_ids=exclude,
                )
                # Only take improvement
                if expanded.token_count > s.token_count:
                    idx = slices.index(s)
                    surplus -= expanded.token_count - s.token_count
                    slices[idx] = expanded

    # Phase 4: Cross-tier dedup (after redistribution so removals stick)
    slices = _dedup_cross_tier(slices)

    total = sum(s.token_count for s in slices)
    return CompiledContext(
        query=query,
        slices=slices,
        total_tokens=total,
        budget=token_budget,
    )


def render_context(compiled: CompiledContext) -> str:
    """Render compiled context as plain text for LLM injection."""
    parts: list[str] = []
    for s in compiled.slices:
        if not s.fragments:
            continue
        parts.append(f"=== {s.name.upper()} ({s.token_count} tokens) ===")
        for frag in s.fragments:
            parts.append(frag)
        parts.append("")

    if not parts:
        return "(no context retrieved)"

    return "\n\n".join(parts)
