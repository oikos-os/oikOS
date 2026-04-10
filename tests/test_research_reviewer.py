"""Tests for research reviewer — list, approve, reject staged results."""

import pytest
from pathlib import Path
from unittest.mock import patch
from core.agency.research.reviewer import ResearchReviewer

SAMPLE_STAGED = """---
topic: Test Topic
sources:
  - https://example.com/1
tokens_used: 500
created: 2026-03-16T12:00:00+00:00
tier: semantic
domain: RESEARCH
status: staged
updated: 2026-03-16
---

# Test Topic

Summary content here.
"""


def _create_staged(tmp_path, filename="test_topic_20260316.md", content=SAMPLE_STAGED):
    staging = tmp_path / "staging"
    staging.mkdir(exist_ok=True)
    f = staging / filename
    f.write_text(content, encoding="utf-8")
    return staging, f


class TestReviewer:
    def test_list_returns_staged_files(self, tmp_path):
        staging, _ = _create_staged(tmp_path)
        reviewer = ResearchReviewer(staging_dir=staging)
        result = reviewer.list_staged()
        assert result["count"] == 1
        assert result["staged"][0]["topic"] == "Test Topic"
        assert "summary_preview" in result["staged"][0]

    def test_list_empty_directory(self, tmp_path):
        staging = tmp_path / "staging"
        staging.mkdir()
        reviewer = ResearchReviewer(staging_dir=staging)
        result = reviewer.list_staged()
        assert result["count"] == 0
        assert result["staged"] == []

    def test_reject_deletes_file(self, tmp_path):
        staging, f = _create_staged(tmp_path)
        reviewer = ResearchReviewer(staging_dir=staging)
        result = reviewer.reject(f.name)
        assert f.name in result["rejected"]
        assert not f.exists()

    def test_reject_all(self, tmp_path):
        staging, _ = _create_staged(tmp_path, "file1.md")
        _create_staged(tmp_path, "file2.md")
        reviewer = ResearchReviewer(staging_dir=staging)
        result = reviewer.reject_all()
        assert result["count"] == 2
        assert len(list(staging.glob("*.md"))) == 0

    def test_reject_nonexistent_returns_error(self, tmp_path):
        staging = tmp_path / "staging"
        staging.mkdir()
        reviewer = ResearchReviewer(staging_dir=staging)
        result = reviewer.reject("nonexistent.md")
        assert result["status"] == "error"

    def test_approve_copies_to_vault(self, tmp_path):
        staging, f = _create_staged(tmp_path)
        vault_dir = tmp_path / "vault" / "knowledge"
        vault_dir.mkdir(parents=True)
        reviewer = ResearchReviewer(staging_dir=staging)
        with patch("core.agency.research.reviewer.TIER_PATHS", {"semantic": vault_dir}), \
             patch("core.agency.research.reviewer.index_vault"):
            result = reviewer.approve(f.name, vault_tier="semantic")
        assert result["status"] == "approved"
        assert (vault_dir / f.name).exists()
        assert not f.exists()

    def test_approve_triggers_reindex(self, tmp_path):
        staging, f = _create_staged(tmp_path)
        vault_dir = tmp_path / "vault" / "knowledge"
        vault_dir.mkdir(parents=True)
        reviewer = ResearchReviewer(staging_dir=staging)
        with patch("core.agency.research.reviewer.TIER_PATHS", {"semantic": vault_dir}), \
             patch("core.agency.research.reviewer.index_vault") as mock_index:
            reviewer.approve(f.name, vault_tier="semantic")
        mock_index.assert_called_once_with(full_rebuild=False)

    def test_approve_invalid_frontmatter_returns_error(self, tmp_path):
        staging, _ = _create_staged(tmp_path, content="# No frontmatter\n\nJust text.")
        reviewer = ResearchReviewer(staging_dir=staging)
        result = reviewer.approve("test_topic_20260316.md")
        assert result["status"] == "error"
        assert "frontmatter" in result["message"].lower()

    def test_approve_invalid_tier_returns_error(self, tmp_path):
        staging, f = _create_staged(tmp_path)
        reviewer = ResearchReviewer(staging_dir=staging)
        with patch("core.agency.research.reviewer.TIER_PATHS", {"semantic": tmp_path}):
            result = reviewer.approve(f.name, vault_tier="nonexistent")
        assert result["status"] == "error"
