"""Tests for calibration system — vault-check and sync-check."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pytest

from core.calibration.vault_freshness import scan_vault, format_report
from core.calibration.sync_manifest import parse_manifest, check_sync


# ── vault-check ──────────────────────────────────────────────────────


def _write_vault_file(path: Path, updated: str, status: str = "ACTIVE"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"---\nupdated: {updated}\nstatus: {status}\n---\n# Test\nContent here.\n",
        encoding="utf-8",
    )


def test_vault_check_no_stale(tmp_path):
    today = date.today().isoformat()
    _write_vault_file(tmp_path / "identity" / "MISSION.md", today)
    _write_vault_file(tmp_path / "knowledge" / "TOOLS.md", today)

    result = scan_vault(tmp_path)
    assert result["stale"] == 0
    assert result["missing_frontmatter"] == 0
    assert result["current"] == 2


def test_vault_check_stale_files(tmp_path):
    today = date.today().isoformat()
    old = (date.today() - timedelta(days=20)).isoformat()
    _write_vault_file(tmp_path / "identity" / "FRESH.md", today)
    _write_vault_file(tmp_path / "knowledge" / "STALE.md", old)

    result = scan_vault(tmp_path)
    assert result["stale"] == 1
    assert result["current"] == 1
    assert result["stale_files"][0]["file"] == "knowledge\\STALE.md" or result["stale_files"][0]["file"] == "knowledge/STALE.md"


def test_vault_check_missing_frontmatter(tmp_path):
    md = tmp_path / "knowledge" / "NO_FM.md"
    md.parent.mkdir(parents=True, exist_ok=True)
    md.write_text("# No frontmatter\nJust content.\n", encoding="utf-8")

    result = scan_vault(tmp_path)
    assert result["missing_frontmatter"] == 1


def test_vault_check_skips_archived(tmp_path):
    old = (date.today() - timedelta(days=30)).isoformat()
    _write_vault_file(tmp_path / "knowledge" / "OLD.md", old, status="ARCHIVED")

    result = scan_vault(tmp_path)
    assert result["stale"] == 0
    assert result["total_active"] == 0


def test_vault_check_skips_backup_dir(tmp_path):
    today = date.today().isoformat()
    _write_vault_file(tmp_path / "identity" / "backup" / "OLD.md", "2020-01-01")
    _write_vault_file(tmp_path / "identity" / "CURRENT.md", today)

    result = scan_vault(tmp_path)
    assert result["current"] == 1
    assert result["stale"] == 0
    assert result["missing_frontmatter"] == 0


def test_vault_format_report():
    result = {
        "stale": 1,
        "stale_files": [{"file": "knowledge/TOOLS.md", "updated": "2026-02-15", "days": 19}],
        "missing_frontmatter": 0,
        "missing_files": [],
        "current": 10,
        "total_active": 11,
        "date": "2026-03-06",
    }
    report = format_report(result)
    assert "TOOLS.md" in report
    assert "19" in report
    assert "Total active files: 11" in report


# ── sync-check ───────────────────────────────────────────────────────


def test_parse_manifest(tmp_path):
    manifest = tmp_path / "SYNC_MANIFEST.md"
    manifest.write_text(
        "# SYNC MANIFEST\n\n"
        "| Document | Primary Location | Mirror Locations | Last Synced |\n"
        "|---|---|---|---|\n"
        "| Doc A | SYNTH Claude Project | vault/knowledge/ | 2026-03-05 |\n"
        "| Doc B | D:\\COMMAND\\CLAUDE.md | \u2014 | 2026-03-05 |\n",
        encoding="utf-8",
    )
    entries = parse_manifest(manifest)
    assert len(entries) == 2
    assert entries[0]["document"] == "Doc A"
    assert entries[1]["last_synced"] == "2026-03-05"


def test_sync_check_all_current(tmp_path):
    manifest = tmp_path / "SYNC_MANIFEST.md"
    target = tmp_path / "test_file.md"
    target.write_text("content", encoding="utf-8")

    manifest.write_text(
        "| Document | Primary Location | Mirror Locations | Last Synced |\n"
        "|---|---|---|---|\n"
        f"| TestDoc | {target} | \u2014 | 2099-12-31 |\n",
        encoding="utf-8",
    )
    result = check_sync(manifest)
    assert len(result["needs_update"]) == 0


def test_sync_check_detects_drift(tmp_path):
    manifest = tmp_path / "SYNC_MANIFEST.md"
    target = tmp_path / "drifted.md"
    target.write_text("updated content", encoding="utf-8")

    manifest.write_text(
        "| Document | Primary Location | Mirror Locations | Last Synced |\n"
        "|---|---|---|---|\n"
        f"| DriftDoc | {target} | vault/knowledge/ | 2020-01-01 |\n",
        encoding="utf-8",
    )
    result = check_sync(manifest)
    assert len(result["needs_update"]) == 1
    assert result["needs_update"][0]["document"] == "DriftDoc"


def test_sync_check_cloud_staleness(tmp_path):
    manifest = tmp_path / "SYNC_MANIFEST.md"
    manifest.write_text(
        "| Document | Primary Location | Mirror Locations | Last Synced |\n"
        "|---|---|---|---|\n"
        "| CloudDoc | SYNTH Claude Project | \u2014 | 2026-03-01 |\n",
        encoding="utf-8",
    )
    result = check_sync(manifest)
    assert len(result["cloud_staleness"]) == 1
    assert result["cloud_staleness"][0]["document"] == "CloudDoc"
