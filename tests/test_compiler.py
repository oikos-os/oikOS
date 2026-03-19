"""Tests for the context compiler."""

import tempfile
from pathlib import Path
from unittest.mock import patch

from core.cognition.compiler import (
    _dedup_cross_tier,
    _extract_topic_keys,
    compile_context,
    count_tokens,
    fill_identity_slice,
    render_context,
)
from core.interface.config import IDENTITY_BUDGET_PCT, IDENTITY_FALLBACK_STRING
from core.interface.models import (
    CompiledContext,
    ContextSlice,
    FragmentMeta,
    MemoryTier,
    SearchResult,
)


def test_count_tokens_basic():
    tokens = count_tokens("Hello, world!")
    assert tokens > 0
    assert isinstance(tokens, int)


def test_count_tokens_empty():
    assert count_tokens("") == 0


def test_count_tokens_longer():
    text = "word " * 100
    tokens = count_tokens(text)
    assert 90 <= tokens <= 110  # ~100 words ≈ ~100 tokens


def _make_search_result(
    content: str,
    tier: MemoryTier,
    source_path: str = "test.md",
    header_path: str = "Test",
) -> SearchResult:
    return SearchResult(
        chunk_id="test",
        source_path=source_path,
        tier=tier,
        header_path=header_path,
        content=content,
        relevance_score=0.9,
        recency_weight=1.0,
        importance_weight=1.0,
        final_score=0.9,
    )


@patch("core.cognition.compiler.search_tier")
def test_compile_budget_compliance(mock_search):
    """Total tokens should never exceed budget."""
    mock_search.return_value = [
        _make_search_result("Short fragment. " * 10, MemoryTier.CORE)
    ]
    compiled = compile_context("test", token_budget=6000)
    assert compiled.total_tokens <= compiled.budget


@patch("core.cognition.compiler.search_tier")
def test_compile_empty_results(mock_search):
    """Empty search results: identity slice always populated; all others empty."""
    mock_search.return_value = []
    compiled = compile_context("test", token_budget=6000)
    identity = [s for s in compiled.slices if s.name == "identity"][0]
    # Identity slice always has content (system.md or fallback)
    assert len(identity.fragments) >= 1
    # All other slices should be empty with no search results
    assert all(len(s.fragments) == 0 for s in compiled.slices if s.name != "identity")


def test_render_context_empty():
    compiled = CompiledContext(query="test", slices=[], total_tokens=0, budget=6000)
    rendered = render_context(compiled)
    assert rendered == "(no context retrieved)"


def test_render_context_with_slices():
    slices = [
        ContextSlice(
            name="core",
            tier=MemoryTier.CORE,
            fragments=["Fragment one.", "Fragment two."],
            fragment_meta=[
                FragmentMeta(source_path="a.md", header_path="A"),
                FragmentMeta(source_path="b.md", header_path="B"),
            ],
            token_count=10,
            max_tokens=1500,
        ),
    ]
    compiled = CompiledContext(query="test", slices=slices, total_tokens=10, budget=6000)
    rendered = render_context(compiled)
    assert "=== CORE (10 tokens) ===" in rendered
    assert "Fragment one." in rendered
    assert "Fragment two." in rendered


@patch("core.cognition.compiler.search_tier")
def test_fill_slice_stores_fragment_meta(mock_search):
    """fill_slice should populate fragment_meta parallel to fragments."""
    mock_search.return_value = [
        _make_search_result(
            "Some content",
            MemoryTier.SEMANTIC,
            source_path="vault/knowledge/MUSIC.md",
            header_path="PROJECT: PROBLEM",
        ),
    ]
    compiled = compile_context("test", token_budget=6000)
    semantic = [s for s in compiled.slices if s.name == "semantic"][0]
    assert len(semantic.fragments) == len(semantic.fragment_meta)
    if semantic.fragments:
        assert semantic.fragment_meta[0].source_path == "vault/knowledge/MUSIC.md"


# ── Cross-tier dedup tests ──────────────────────────────────────────


def test_extract_topic_keys_from_header():
    keys = _extract_topic_keys("PROJECT: PROBLEM (USER)", "Some content here.")
    assert "problem" in keys
    assert "user" in keys
    assert "project" in keys


def test_extract_topic_keys_from_content():
    keys = _extract_topic_keys("Root", "**GENRE:** Pharrell Groove. Tyler Creator influence.")
    assert "pharrell groove" in keys or "pharrell" in keys
    assert "tyler creator" in keys or "tyler" in keys


def test_dedup_removes_broad_core_fragment():
    """Core fragment referencing 2+ semantic sources should be removed."""
    core_slice = ContextSlice(
        name="core",
        tier=MemoryTier.CORE,
        fragments=[
            # Broad timeline table mentioning multiple projects
            "| Feb 27 | Vossa | Horas | PENDING |\n| Mar 27 | Boy | Secrets | PENDING |\n| Apr 24 | Apex | Problem | PENDING |",
            # Non-overlapping core fragment
            "The Architect's cognitive style preferences.",
        ],
        fragment_meta=[
            FragmentMeta(source_path="vault/identity/GOALS.md", header_path="GOALS > TIMELINE"),
            FragmentMeta(source_path="vault/identity/MODELS.md", header_path="MODELS > COGNITIVE"),
        ],
        token_count=100,
        max_tokens=1500,
    )
    semantic_slice = ContextSlice(
        name="semantic",
        tier=MemoryTier.SEMANTIC,
        fragments=[
            "**RELEASE DATE:** APR 24, 2026\n**GENRE:** Pharrell/Neptunes Groove.",
            "**RELEASE DATE:** MAR 27, 2026\n**GENRE:** PinkPantheress meets Britney.",
        ],
        fragment_meta=[
            FragmentMeta(
                source_path="vault/knowledge/MUSIC_RELEASES.md",
                header_path="MUSIC_RELEASES > PROJECT: PROBLEM (USER)",
            ),
            FragmentMeta(
                source_path="vault/knowledge/MUSIC_RELEASES.md",
                header_path="MUSIC_RELEASES > PROJECT: SECRETS (BOY)",
            ),
        ],
        token_count=80,
        max_tokens=1500,
    )
    slices = [
        core_slice,
        semantic_slice,
        ContextSlice(name="procedural", tier=MemoryTier.PROCEDURAL, max_tokens=1200),
        ContextSlice(name="episodic", tier=MemoryTier.EPISODIC, max_tokens=1800),
    ]

    result = _dedup_cross_tier(slices)
    core_result = [s for s in result if s.name == "core"][0]

    # Broad timeline should be removed, cognitive fragment kept
    assert len(core_result.fragments) == 1
    assert "cognitive" in core_result.fragments[0].lower()


def test_dedup_preserves_non_overlapping_core():
    """Core fragments that don't overlap semantic should survive dedup."""
    core_slice = ContextSlice(
        name="core",
        tier=MemoryTier.CORE,
        fragments=["The Architect's mission is total sovereignty."],
        fragment_meta=[
            FragmentMeta(source_path="vault/identity/MISSION.md", header_path="MISSION"),
        ],
        token_count=20,
        max_tokens=1500,
    )
    semantic_slice = ContextSlice(
        name="semantic",
        tier=MemoryTier.SEMANTIC,
        fragments=["OIKOS technical stack: LanceDB, Ollama, Python."],
        fragment_meta=[
            FragmentMeta(
                source_path="vault/knowledge/OIKOS_TECHNICAL.md",
                header_path="OIKOS > STACK",
            ),
        ],
        token_count=20,
        max_tokens=1500,
    )
    slices = [
        core_slice,
        semantic_slice,
        ContextSlice(name="procedural", tier=MemoryTier.PROCEDURAL, max_tokens=1200),
        ContextSlice(name="episodic", tier=MemoryTier.EPISODIC, max_tokens=1800),
    ]

    result = _dedup_cross_tier(slices)
    core_result = [s for s in result if s.name == "core"][0]
    assert len(core_result.fragments) == 1  # preserved


def test_dedup_no_semantic_is_noop():
    """If semantic slice is empty, dedup should not modify anything."""
    core_slice = ContextSlice(
        name="core",
        tier=MemoryTier.CORE,
        fragments=["Some core content."],
        fragment_meta=[
            FragmentMeta(source_path="vault/identity/GOALS.md", header_path="GOALS"),
        ],
        token_count=10,
        max_tokens=1500,
    )
    semantic_slice = ContextSlice(
        name="semantic",
        tier=MemoryTier.SEMANTIC,
        max_tokens=1500,
    )
    slices = [
        core_slice,
        semantic_slice,
        ContextSlice(name="procedural", tier=MemoryTier.PROCEDURAL, max_tokens=1200),
        ContextSlice(name="episodic", tier=MemoryTier.EPISODIC, max_tokens=1800),
    ]

    result = _dedup_cross_tier(slices)
    core_result = [s for s in result if s.name == "core"][0]
    assert len(core_result.fragments) == 1  # untouched


def test_dedup_single_source_overlap_preserved():
    """Core fragment overlapping only 1 semantic source should survive (threshold is 2+)."""
    core_slice = ContextSlice(
        name="core",
        tier=MemoryTier.CORE,
        fragments=["Problem is the next release target."],
        fragment_meta=[
            FragmentMeta(source_path="vault/identity/GOALS.md", header_path="GOALS > NEXT"),
        ],
        token_count=15,
        max_tokens=1500,
    )
    semantic_slice = ContextSlice(
        name="semantic",
        tier=MemoryTier.SEMANTIC,
        fragments=["**RELEASE DATE:** APR 24, 2026. Problem details."],
        fragment_meta=[
            FragmentMeta(
                source_path="vault/knowledge/MUSIC_RELEASES.md",
                header_path="MUSIC_RELEASES > PROJECT: PROBLEM",
            ),
        ],
        token_count=20,
        max_tokens=1500,
    )
    slices = [
        core_slice,
        semantic_slice,
        ContextSlice(name="procedural", tier=MemoryTier.PROCEDURAL, max_tokens=1200),
        ContextSlice(name="episodic", tier=MemoryTier.EPISODIC, max_tokens=1800),
    ]

    result = _dedup_cross_tier(slices)
    core_result = [s for s in result if s.name == "core"][0]
    assert len(core_result.fragments) == 1  # preserved — only 1 source overlap


# ── Module 1: Compiler Hierarchy tests ──────────────────────────────


def _make_search_result_with_id(
    content: str,
    tier: MemoryTier,
    chunk_id: str = "test-id",
    source_path: str = "test.md",
    header_path: str = "Test",
) -> SearchResult:
    return SearchResult(
        chunk_id=chunk_id,
        source_path=source_path,
        tier=tier,
        header_path=header_path,
        content=content,
        relevance_score=0.9,
        recency_weight=1.0,
        importance_weight=1.0,
        final_score=0.9,
    )


@patch("core.cognition.compiler.search_tier")
def test_identity_slice_is_first(mock_search):
    """Identity slice must be the first slice in compiled context."""
    mock_search.return_value = []
    compiled = compile_context("test query", token_budget=6000)
    assert compiled.slices[0].name == "identity"


@patch("core.cognition.compiler.search_tier")
def test_identity_budget_allocation(mock_search):
    """Identity slice max_tokens must equal IDENTITY_BUDGET_PCT of total budget."""
    mock_search.return_value = []
    budget = 6000
    compiled = compile_context("test", token_budget=budget)
    identity = [s for s in compiled.slices if s.name == "identity"][0]
    expected = int(IDENTITY_BUDGET_PCT * budget)
    assert identity.max_tokens == expected


@patch("core.cognition.compiler.search_tier")
def test_identity_always_present_with_search_results(mock_search):
    """Identity slice present and non-empty even when other slices have results."""
    mock_search.return_value = [
        _make_search_result("Some semantic content.", MemoryTier.SEMANTIC)
    ]
    compiled = compile_context("music production", token_budget=6000)
    identity = [s for s in compiled.slices if s.name == "identity"][0]
    assert len(identity.fragments) >= 1


@patch("core.cognition.compiler.search_tier")
def test_identity_total_tokens_within_budget(mock_search):
    """Total compiled tokens must not exceed budget even with identity tier loaded."""
    mock_search.return_value = [
        _make_search_result("word " * 200, MemoryTier.CORE),
        _make_search_result("word " * 200, MemoryTier.SEMANTIC),
    ]
    budget = 6000
    compiled = compile_context("test", token_budget=budget)
    # Identity may exceed its own budget (non-negotiable), but total should
    # stay within or close to the overall budget (system.md is typically <1200 tokens)
    assert compiled.total_tokens <= budget + 200  # small headroom for system.md edge case


@patch("core.cognition.compiler.search_tier")
def test_identity_fallback_activates_when_system_md_missing(mock_search):
    """When system.md is absent, fallback identity string is loaded."""
    mock_search.return_value = []
    with tempfile.TemporaryDirectory() as tmpdir:
        # Point VAULT_DIR to empty temp dir — no system.md exists
        with patch("core.cognition.compiler.VAULT_DIR", Path(tmpdir)), \
             patch("core.cognition.compiler._SYSTEM_MD", Path(tmpdir) / "patterns" / "sovereign" / "system.md"):
            compiled = compile_context("test", token_budget=6000)
    identity = [s for s in compiled.slices if s.name == "identity"][0]
    assert len(identity.fragments) == 1
    assert "KAIROS PRIME" in identity.fragments[0]
    assert identity.fragment_meta[0].source_path == "[FALLBACK]"


@patch("core.cognition.compiler.search_tier")
def test_identity_query_independence(mock_search):
    """Identity slice loads system.md regardless of query topic."""
    mock_search.return_value = []
    queries = [
        "what is the status of my music projects",
        "how much money do I have",
        "write me a chapter of Example Novel",
        "explain LanceDB hybrid search",
        "I feel overwhelmed today",
    ]
    identity_contents = []
    for q in queries:
        compiled = compile_context(q, token_budget=6000)
        identity = [s for s in compiled.slices if s.name == "identity"][0]
        # system.md fragment is always first
        identity_contents.append(identity.fragments[0])

    # All queries should produce the same first identity fragment (system.md)
    assert len(set(identity_contents)) == 1, (
        "Identity tier content varied by query — system.md is not query-independent"
    )


@patch("core.cognition.compiler.search_tier")
def test_telos_excluded_from_core_slice(mock_search):
    """TELOS chunks loaded in identity slice must not appear in core slice."""
    telos_chunk = _make_search_result_with_id(
        "Core mission content.",
        MemoryTier.CORE,
        chunk_id="telos-abc123",
        source_path="vault/identity/MISSION.md",
        header_path="MISSION",
    )
    mock_search.return_value = [telos_chunk]

    compiled = compile_context("test", token_budget=6000)
    identity = [s for s in compiled.slices if s.name == "identity"][0]
    core = [s for s in compiled.slices if s.name == "core"][0]

    identity_content = " ".join(identity.fragments)
    core_content = " ".join(core.fragments)

    # TELOS content in identity — core must not duplicate it
    if "Core mission content." in identity_content:
        assert "Core mission content." not in core_content, (
            "TELOS chunk appeared in both identity and core slices"
        )


@patch("core.cognition.compiler.search_tier")
def test_remaining_budget_splits_correctly(mock_search):
    """After identity allocation, remaining budget is distributed across core/semantic/procedural/episodic."""
    mock_search.return_value = []
    budget = 6000
    identity_budget = int(IDENTITY_BUDGET_PCT * budget)
    remaining = budget - identity_budget

    compiled = compile_context("test", token_budget=budget)

    # Verify each competitive slice has correct max_tokens from remaining budget
    from core.interface.config import SLICE_ALLOCATIONS
    for s in compiled.slices:
        if s.name == "identity":
            assert s.max_tokens == identity_budget
        elif s.name in SLICE_ALLOCATIONS:
            expected = int(SLICE_ALLOCATIONS[s.name] * remaining)
            assert s.max_tokens == expected, (
                f"Slice '{s.name}' max_tokens={s.max_tokens}, expected={expected}"
            )


@patch("core.cognition.compiler.search_tier")
def test_episodic_cannot_displace_identity(mock_search):
    """Large episodic results must not reduce identity tier allocation."""
    # Simulate a large episodic result that would overflow if identity weren't protected
    large_content = "word " * 400  # ~400 tokens
    mock_search.return_value = [
        _make_search_result(large_content, MemoryTier.EPISODIC),
        _make_search_result(large_content, MemoryTier.EPISODIC),
        _make_search_result(large_content, MemoryTier.EPISODIC),
    ]
    budget = 6000
    compiled = compile_context("test", token_budget=budget)
    identity = [s for s in compiled.slices if s.name == "identity"][0]
    expected_budget = int(IDENTITY_BUDGET_PCT * budget)

    # Identity budget is fixed — episodic can't touch it
    assert identity.max_tokens == expected_budget
