"""Tests for pattern scanner — activation gate, Optimist/Pessimist, resonance, blip management."""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from core.interface.models import Blip
from core.autonomic.scanner import (
    _blip_id,
    _load_all_blips,
    _parse_optimist_response,
    _parse_pessimist_response,
    _save_blip,
    check_activation_gate,
    compute_resonance,
    load_undelivered_blips,
    mark_blips_delivered,
    run_scan,
)


def _make_vault(tmp_path, files_per_domain: dict[str, int], file_size: int = 600) -> Path:
    """Create a vault directory structure with files of given size."""
    vault = tmp_path / "vault"
    for domain, count in files_per_domain.items():
        domain_dir = vault / domain
        domain_dir.mkdir(parents=True, exist_ok=True)
        for i in range(count):
            f = domain_dir / f"file_{i}.md"
            f.write_text("x" * file_size, encoding="utf-8")
    return vault


def _make_blip(blip_id: str = "test123", delivered: bool = False, days_until_expiry: int = 15) -> Blip:
    now = datetime.now(timezone.utc)
    return Blip(
        blip_id=blip_id,
        generated_at=now.isoformat(),
        chunk_a={"chunk_id": "a1", "source_path": "vault/identity/A.md", "tier": "core", "content_preview": "test"},
        chunk_b={"chunk_id": "b1", "source_path": "vault/knowledge/B.md", "tier": "semantic", "content_preview": "test"},
        optimist_score=75.0,
        pessimist_kill_probability=20.0,
        resonance=60.0,
        observation="Test connection",
        delivered=delivered,
        expires_at=(now + timedelta(days=days_until_expiry)).isoformat(),
    )


# ── Activation gate ──────────────────────────────────────────────────


def test_gate_fails_insufficient_files(tmp_path):
    """<15 files → gate inactive."""
    vault = _make_vault(tmp_path, {"identity": 2, "patterns": 2, "knowledge": 2})
    result = check_activation_gate(vault)
    assert result["active"] is False
    assert "Insufficient files" in result["reason"]


def test_gate_fails_insufficient_domains(tmp_path):
    """<3 domains → gate inactive."""
    vault = _make_vault(tmp_path, {"identity": 8, "patterns": 8})
    result = check_activation_gate(vault)
    assert result["active"] is False
    assert "Insufficient domains" in result["reason"]


def test_gate_passes_sufficient_content(tmp_path):
    """15+ files across 3+ domains → gate active."""
    vault = _make_vault(tmp_path, {"identity": 5, "patterns": 5, "knowledge": 5})
    result = check_activation_gate(vault)
    assert result["active"] is True
    assert result["stats"]["files"] == 15
    assert result["stats"]["domains"] == 3


def test_gate_ignores_small_files(tmp_path):
    """Files <500 bytes don't count."""
    vault = _make_vault(tmp_path, {"identity": 5, "patterns": 5, "knowledge": 5}, file_size=100)
    result = check_activation_gate(vault)
    assert result["active"] is False


# ── Resonance ────────────────────────────────────────────────────────


def test_resonance_calculation():
    """80 * (1 - 25/100) = 60."""
    assert compute_resonance(80.0, 25.0) == 60.0


def test_resonance_none_when_pessimist_skipped():
    """Kill probability None → resonance None."""
    assert compute_resonance(80.0, None) is None


def test_resonance_zero_kill():
    """Kill probability 0 → resonance = optimist score."""
    assert compute_resonance(75.0, 0.0) == 75.0


# ── Response parsing ─────────────────────────────────────────────────


def test_parse_optimist_response():
    """Extracts SCORE and OBSERVATION."""
    text = "SCORE: 72\nOBSERVATION: Music production discipline mirrors code refactoring cycles."
    result = _parse_optimist_response(text)
    assert result["score"] == 72.0
    assert "Music production" in result["observation"]


def test_parse_pessimist_response():
    """Extracts KILL_PROBABILITY and REASONING."""
    text = "KILL_PROBABILITY: 30\nREASONING: Connection is surface-level analogy."
    result = _parse_pessimist_response(text)
    assert result["kill_probability"] == 30.0
    assert "surface-level" in result["reasoning"]


def test_parse_optimist_clamped():
    """Score >100 clamped to 100."""
    text = "SCORE: 150\nOBSERVATION: test"
    result = _parse_optimist_response(text)
    assert result["score"] == 100.0


# ── Blip persistence ────────────────────────────────────────────────


def test_blip_save_load_round_trip(tmp_path, monkeypatch):
    """Save and reload a blip."""
    log_file = tmp_path / "blips.jsonl"
    monkeypatch.setattr("core.autonomic.scanner.SCANNER_BLIP_LOG", log_file)

    blip = _make_blip("test_rt")
    _save_blip(blip)

    loaded = _load_all_blips()
    assert len(loaded) == 1
    assert loaded[0].blip_id == "test_rt"
    assert loaded[0].observation == "Test connection"


def test_load_filters_delivered(tmp_path, monkeypatch):
    """Delivered blips excluded from undelivered list."""
    log_file = tmp_path / "blips.jsonl"
    monkeypatch.setattr("core.autonomic.scanner.SCANNER_BLIP_LOG", log_file)

    _save_blip(_make_blip("a1", delivered=False))
    _save_blip(_make_blip("a2", delivered=True))

    undelivered = load_undelivered_blips()
    assert len(undelivered) == 1
    assert undelivered[0].blip_id == "a1"


def test_load_filters_expired(tmp_path, monkeypatch):
    """Expired blips excluded from undelivered list."""
    log_file = tmp_path / "blips.jsonl"
    monkeypatch.setattr("core.autonomic.scanner.SCANNER_BLIP_LOG", log_file)

    _save_blip(_make_blip("fresh", days_until_expiry=15))
    _save_blip(_make_blip("stale", days_until_expiry=-1))

    undelivered = load_undelivered_blips()
    assert len(undelivered) == 1
    assert undelivered[0].blip_id == "fresh"


def test_mark_delivered(tmp_path, monkeypatch):
    """Mark blips as delivered rewrites JSONL."""
    log_file = tmp_path / "blips.jsonl"
    monkeypatch.setattr("core.autonomic.scanner.SCANNER_BLIP_LOG", log_file)

    _save_blip(_make_blip("x1", delivered=False))
    _save_blip(_make_blip("x2", delivered=False))

    mark_blips_delivered(["x1"])

    all_blips = _load_all_blips()
    assert all_blips[0].blip_id == "x1"
    assert all_blips[0].delivered is True
    assert all_blips[1].blip_id == "x2"
    assert all_blips[1].delivered is False


# ── Run scan (mocked inference) ─────────────────────────────────────


def test_run_scan_gate_inactive(tmp_path):
    """Gate fails → empty scan result."""
    vault = _make_vault(tmp_path, {"identity": 1})
    result = run_scan(vault_dir=vault)
    assert result["pairs_evaluated"] == 0
    assert result["blips"] == []
    assert "gate_reason" in result


def test_run_scan_with_mocked_pairs(tmp_path, monkeypatch):
    """Full scan with mocked pair selection and inference."""
    vault = _make_vault(tmp_path, {"identity": 5, "patterns": 5, "knowledge": 5})
    log_file = tmp_path / "blips.jsonl"
    monkeypatch.setattr("core.autonomic.scanner.SCANNER_BLIP_LOG", log_file)

    mock_pairs = [(
        {"chunk_id": "c1", "source_path": "vault/identity/A.md", "tier": "core", "content_preview": "test A"},
        {"chunk_id": "c2", "source_path": "vault/knowledge/B.md", "tier": "semantic", "content_preview": "test B"},
    )]

    with patch("core.autonomic.scanner._select_cross_domain_pairs", return_value=mock_pairs), \
         patch("core.autonomic.scanner._optimist_pass", return_value={"score": 75.0, "observation": "Found link"}), \
         patch("core.autonomic.scanner._pessimist_pass", return_value={"kill_probability": 10.0, "reasoning": "Valid"}):
        result = run_scan(vault_dir=vault)

    assert result["pairs_evaluated"] == 1
    assert result["pairs_above_threshold"] == 1
    assert len(result["blips"]) == 1
    assert result["blips"][0].resonance == 75.0 * (1 - 10.0 / 100)
