"""Tests for core.agency.consolidation — Memory Consolidation Agent."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from core.interface.models import PromotionProposal

# Valid LLM response for mocking
_MOCK_LLM_RESPONSE = json.dumps([
    {
        "insight_type": "decision",
        "action": "CREATE",
        "target_path": "vault/knowledge/decisions.md",
        "target_section": "Architecture",
        "extracted_claim": "LanceDB chosen over ChromaDB for vector storage",
        "evidence": "Performance benchmarks in session",
        "confidence": 0.9,
        "strategic_divergence": False,
        "conflict_with": None,
    }
])

_MOCK_LESSON_RESPONSE = json.dumps([
    {
        "insight_type": "lesson",
        "action": "CREATE",
        "target_path": "vault/knowledge/LEARNINGS.md",
        "target_section": "ARCHITECTURE",
        "extracted_claim": "**L-021: Always verify model version before deployment.** Deployed wrong model version causing inference failures. (Session 2026-03-02, 2026-03-02)",
        "evidence": "Error fixed in session — model was gemini-3.1 (nonexistent)",
        "confidence": 0.85,
        "strategic_divergence": False,
        "conflict_with": None,
    }
])

_MOCK_DIVERGENCE_RESPONSE = json.dumps([
    {
        "insight_type": "decision",
        "action": "CREATE",
        "target_path": "vault/knowledge/decisions.md",
        "target_section": None,
        "extracted_claim": "Abandon local inference and go fully cloud-based",
        "evidence": "Contradicts MISSION.md Section 1: total sovereignty and local-first",
        "confidence": 0.95,
        "strategic_divergence": True,
        "conflict_with": None,
    }
])

_MOCK_LOW_CONFIDENCE = json.dumps([
    {
        "insight_type": "fact",
        "action": "CREATE",
        "target_path": "vault/knowledge/facts.md",
        "extracted_claim": "Maybe consider using Redis",
        "evidence": "Mentioned once in passing",
        "confidence": 0.3,
        "strategic_divergence": False,
        "conflict_with": None,
    }
])


@pytest.fixture
def consolidation_env(tmp_path):
    """Set up isolated consolidation environment."""
    logs_dir = tmp_path / "logs" / "sessions" / "2026-03-02"
    logs_dir.mkdir(parents=True)
    consol_dir = tmp_path / "logs" / "consolidation"
    consol_dir.mkdir(parents=True)
    vault_dir = tmp_path / "vault"
    (vault_dir / "knowledge").mkdir(parents=True)
    (vault_dir / "identity").mkdir(parents=True)
    (vault_dir / "patterns" / "consolidate_memory").mkdir(parents=True)

    # Write a session log
    session_file = logs_dir / "2026-03-02_KP-CLAUDE.md"
    session_file.write_text("# Session\nWe decided to use LanceDB.", encoding="utf-8")

    # Write Fabric pattern
    pattern = vault_dir / "patterns" / "consolidate_memory" / "system.md"
    pattern.write_text("You are the Memory Consolidation Agent.", encoding="utf-8")

    # Write strategic files
    (vault_dir / "identity" / "GOALS.md").write_text("# GOALS\nLocal-first.", encoding="utf-8")
    (vault_dir / "identity" / "MISSION.md").write_text("# MISSION\nSovereignty.", encoding="utf-8")

    proposals_log = consol_dir / "proposals.jsonl"
    processed_file = consol_dir / "processed_sessions.json"

    return {
        "tmp_path": tmp_path,
        "logs_dir": tmp_path / "logs" / "sessions",
        "consol_dir": consol_dir,
        "vault_dir": vault_dir,
        "session_file": session_file,
        "proposals_log": proposals_log,
        "processed_file": processed_file,
    }


def _patch_config(env):
    """Return a dict of config patches for the consolidation module."""
    return {
        "LOGS_DIR": env["logs_dir"],
        "CONSOLIDATION_LOG_DIR": env["consol_dir"],
        "CONSOLIDATION_PROPOSALS_LOG": env["proposals_log"],
        "PROCESSED_SESSIONS_FILE": env["processed_file"],
        "VAULT_DIR": env["vault_dir"],
        "_STRATEGIC_FILES": [
            env["vault_dir"] / "identity" / "GOALS.md",
            env["vault_dir"] / "identity" / "MISSION.md",
        ],
    }


# ── Test 1: Scan produces proposals from session logs ─────────────────
def test_scan_produces_proposals(consolidation_env):
    env = consolidation_env
    patches = _patch_config(env)

    mock_generate = MagicMock(return_value={"response": _MOCK_LLM_RESPONSE})

    with patch.multiple("core.agency.consolidation", **patches), \
         patch("core.cognition.inference.generate_local", mock_generate), \
         patch("core.agency.consolidation._check_duplicate", return_value={"is_duplicate": False, "status": "pending", "conflict_with": None}):
        from core.agency.consolidation import run_consolidation
        result = run_consolidation()

    assert result["files_processed"] >= 1
    assert result["proposals_generated"] >= 1
    assert env["proposals_log"].exists()


# ── Test 2: Confidence filter excludes low-confidence proposals ───────
def test_confidence_filter(consolidation_env):
    env = consolidation_env
    patches = _patch_config(env)

    mock_generate = MagicMock(return_value={"response": _MOCK_LOW_CONFIDENCE})

    with patch.multiple("core.agency.consolidation", **patches), \
         patch("core.cognition.inference.generate_local", mock_generate), \
         patch("core.agency.consolidation._check_duplicate", return_value={"is_duplicate": False, "status": "pending", "conflict_with": None}):
        from core.agency.consolidation import run_consolidation
        result = run_consolidation()

    assert result["proposals_generated"] == 0


# ── Test 3: Approve flow writes to vault ──────────────────────────────
def test_approve_writes_to_vault(consolidation_env):
    env = consolidation_env
    proposals_log = env["proposals_log"]
    vault_dir = env["vault_dir"]

    prop = PromotionProposal(
        proposal_id="test-001",
        source_session_ids=["test.md"],
        insight_type="decision",
        action="CREATE",
        summary="LanceDB chosen",
        draft_content="LanceDB chosen over ChromaDB",
        target_path="vault/knowledge/decisions.md",
        target_section=None,
        conflict_with=None,
        strategic_divergence=False,
        heuristics_triggered=["test"],
        status="pending",
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    proposals_log.write_text(prop.model_dump_json() + "\n", encoding="utf-8")

    patches = _patch_config(env)
    with patch.multiple("core.agency.consolidation", **patches):
        from core.agency.consolidation import mark_proposal_status
        mark_proposal_status("test-001", "approved", apply=True)

    target = vault_dir / "knowledge" / "decisions.md"
    assert target.exists()
    assert "LanceDB chosen over ChromaDB" in target.read_text(encoding="utf-8")


# ── Test 4: Reject marks without vault modification ───────────────────
def test_reject_no_vault_write(consolidation_env):
    env = consolidation_env
    proposals_log = env["proposals_log"]
    vault_dir = env["vault_dir"]

    prop = PromotionProposal(
        proposal_id="test-002",
        source_session_ids=["test.md"],
        insight_type="fact",
        action="CREATE",
        summary="Redis considered",
        draft_content="Redis for caching",
        target_path="vault/knowledge/decisions.md",
        target_section=None,
        conflict_with=None,
        strategic_divergence=False,
        heuristics_triggered=["test"],
        status="pending",
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    proposals_log.write_text(prop.model_dump_json() + "\n", encoding="utf-8")

    patches = _patch_config(env)
    with patch.multiple("core.agency.consolidation", **patches):
        from core.agency.consolidation import mark_proposal_status
        mark_proposal_status("test-002", "rejected", apply=False)

    target = vault_dir / "knowledge" / "decisions.md"
    assert not target.exists()

    # Verify status updated in log
    content = proposals_log.read_text(encoding="utf-8").strip()
    data = json.loads(content)
    assert data["status"] == "rejected"


# ── Test 5: Dedup suppresses duplicate proposals ─────────────────────
def test_dedup_suppresses_duplicates(consolidation_env):
    env = consolidation_env
    patches = _patch_config(env)

    mock_generate = MagicMock(return_value={"response": _MOCK_LLM_RESPONSE})

    with patch.multiple("core.agency.consolidation", **patches), \
         patch("core.cognition.inference.generate_local", mock_generate), \
         patch("core.agency.consolidation._check_duplicate", return_value={"is_duplicate": True, "status": "duplicate", "conflict_with": "chunk-abc"}):
        from core.agency.consolidation import run_consolidation
        result = run_consolidation()

    assert result["proposals_generated"] == 0


# ── Test 6: Strategic divergence flag set on contradictions ───────────
def test_strategic_divergence_flag(consolidation_env):
    env = consolidation_env
    patches = _patch_config(env)

    mock_generate = MagicMock(return_value={"response": _MOCK_DIVERGENCE_RESPONSE})

    with patch.multiple("core.agency.consolidation", **patches), \
         patch("core.cognition.inference.generate_local", mock_generate), \
         patch("core.agency.consolidation._check_duplicate", return_value={"is_duplicate": False, "status": "pending", "conflict_with": None}):
        from core.agency.consolidation import run_consolidation
        run_consolidation()

    content = env["proposals_log"].read_text(encoding="utf-8").strip()
    prop = PromotionProposal.model_validate_json(content)
    assert prop.strategic_divergence is True


# ── Test 7: LEARNINGS proposals generated for lessons ─────────────────
def test_learnings_proposals(consolidation_env):
    env = consolidation_env
    patches = _patch_config(env)

    mock_generate = MagicMock(return_value={"response": _MOCK_LESSON_RESPONSE})

    with patch.multiple("core.agency.consolidation", **patches), \
         patch("core.cognition.inference.generate_local", mock_generate), \
         patch("core.agency.consolidation._check_duplicate", return_value={"is_duplicate": False, "status": "pending", "conflict_with": None}):
        from core.agency.consolidation import run_consolidation
        run_consolidation()

    content = env["proposals_log"].read_text(encoding="utf-8").strip()
    prop = PromotionProposal.model_validate_json(content)
    assert prop.insight_type == "lesson"
    assert "LEARNINGS.md" in prop.target_path


# ── Test 8: Progress callback fires during scan ──────────────────────
def test_progress_callback(consolidation_env):
    env = consolidation_env
    patches = _patch_config(env)

    mock_generate = MagicMock(return_value={"response": "[]"})
    progress_messages = []

    with patch.multiple("core.agency.consolidation", **patches), \
         patch("core.cognition.inference.generate_local", mock_generate):
        from core.agency.consolidation import run_consolidation
        run_consolidation(on_progress=lambda msg: progress_messages.append(msg))

    assert len(progress_messages) >= 1
    assert "Scanning session" in progress_messages[0]


# ── Test 9: Lookback window excludes old sessions ────────────────────
def test_lookback_window(consolidation_env):
    env = consolidation_env
    patches = _patch_config(env)

    # Create an old session file (30 days ago)
    old_dir = env["logs_dir"] / "2026-02-01"
    old_dir.mkdir(parents=True)
    old_file = old_dir / "old_session.md"
    old_file.write_text("# Old session\nStale data.", encoding="utf-8")

    # Set mtime to 30 days ago
    old_time = (datetime.now(timezone.utc) - timedelta(days=30)).timestamp()
    os.utime(old_file, (old_time, old_time))

    mock_generate = MagicMock(return_value={"response": _MOCK_LLM_RESPONSE})

    with patch.multiple("core.agency.consolidation", **patches), \
         patch("core.cognition.inference.generate_local", mock_generate), \
         patch("core.agency.consolidation._check_duplicate", return_value={"is_duplicate": False, "status": "pending", "conflict_with": None}):
        from core.agency.consolidation import run_consolidation
        result = run_consolidation()

    # Only the recent file should be processed, not the old one
    assert result["files_processed"] == 1
    assert mock_generate.call_count == 1


# ── Test 10: Empty session skipped without proposal ───────────────────
def test_empty_session_skipped(consolidation_env):
    env = consolidation_env

    # Overwrite session file with empty content
    env["session_file"].write_text("", encoding="utf-8")

    patches = _patch_config(env)
    mock_generate = MagicMock(return_value={"response": "[]"})

    with patch.multiple("core.agency.consolidation", **patches), \
         patch("core.cognition.inference.generate_local", mock_generate):
        from core.agency.consolidation import run_consolidation
        result = run_consolidation()

    # Empty file should be marked processed but no LLM call
    mock_generate.assert_not_called()
    assert result["proposals_generated"] == 0


# ── Test 11: Already-scanned sessions not re-processed ────────────────
def test_already_scanned_skipped(consolidation_env):
    env = consolidation_env
    patches = _patch_config(env)

    # Pre-populate processed sessions
    rel_path = str(env["session_file"].relative_to(env["tmp_path"]))
    env["processed_file"].write_text(
        json.dumps({"processed": [rel_path]}), encoding="utf-8"
    )

    mock_generate = MagicMock(return_value={"response": "[]"})

    with patch.multiple("core.agency.consolidation", **patches), \
         patch("core.cognition.inference.generate_local", mock_generate):
        from core.agency.consolidation import run_consolidation
        result = run_consolidation()

    mock_generate.assert_not_called()
    assert result["files_processed"] == 0


# ── Test 12: Briefing count returns pending proposals ─────────────────
def test_briefing_count(consolidation_env):
    env = consolidation_env
    proposals_log = env["proposals_log"]

    props = []
    for i, status in enumerate(["pending", "pending", "approved", "rejected"]):
        prop = PromotionProposal(
            proposal_id=f"bc-{i:03d}",
            source_session_ids=["test.md"],
            insight_type="fact",
            action="CREATE",
            summary=f"Fact {i}",
            draft_content=f"Content {i}",
            target_path="vault/knowledge/test.md",
            conflict_with=None,
            strategic_divergence=False,
            heuristics_triggered=["test"],
            status=status,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        props.append(prop)

    proposals_log.write_text(
        "\n".join(p.model_dump_json() for p in props) + "\n", encoding="utf-8"
    )

    patches = _patch_config(env)
    with patch.multiple("core.agency.consolidation", **patches):
        from core.agency.consolidation import load_pending_proposals
        pending = load_pending_proposals()

    assert len(pending) == 2


# ── Test 13: Max files per pass respected ─────────────────────────────
def test_max_files_per_pass(consolidation_env):
    env = consolidation_env
    patches = _patch_config(env)

    # Create 8 session files (exceeds CONSOLIDATION_MAX_FILES_PER_PASS=5)
    for i in range(8):
        f = env["logs_dir"] / "2026-03-02" / f"session_{i}.md"
        f.write_text(f"# Session {i}\nContent {i}.", encoding="utf-8")

    mock_generate = MagicMock(return_value={"response": "[]"})

    with patch.multiple("core.agency.consolidation", **patches), \
         patch("core.cognition.inference.generate_local", mock_generate):
        from core.agency.consolidation import run_consolidation
        result = run_consolidation()

    assert result["files_processed"] <= 5
