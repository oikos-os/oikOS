"""Tests for confidence threshold calibration."""

import json

from core.autonomic.calibration import (
    MIN_SAMPLES_PRELIMINARY,
    calibration_report,
    compute_accuracy_curve,
    load_rated_entries,
    recommend_threshold,
)


def _write_log(tmp_path, entries):
    """Helper: write entries to a routing log JSONL file."""
    log_file = tmp_path / "2026-02-13.jsonl"
    with open(log_file, "w", encoding="utf-8") as f:
        for e in entries:
            f.write(json.dumps(e) + "\n")


def _make_entry(confidence, accepted):
    return {
        "timestamp": "2026-02-13T00:00:00",
        "query_hash": "abc",
        "confidence_score": confidence,
        "route_taken": "local",
        "pii_detected": False,
        "reason": "test",
        "user_accepted": accepted,
    }


# ── load_rated_entries ───────────────────────────────────────────────


def test_load_rated_entries_filters_nulls(tmp_path):
    entries = [
        _make_entry(70.0, True),
        _make_entry(50.0, None),  # skip — should be excluded
        _make_entry(80.0, False),
    ]
    _write_log(tmp_path, entries)
    rated = load_rated_entries(tmp_path)
    assert len(rated) == 2


def test_load_rated_entries_empty_dir(tmp_path):
    assert load_rated_entries(tmp_path) == []


# ── compute_accuracy_curve ───────────────────────────────────────────


def test_accuracy_curve_basic():
    entries = [
        _make_entry(75.0, True),
        _make_entry(72.0, True),
        _make_entry(78.0, False),
        _make_entry(25.0, False),
        _make_entry(22.0, True),
    ]
    curve = compute_accuracy_curve(entries, buckets=10)
    assert len(curve) == 10

    # Bucket 70-80 should have 3 entries, 2 accepted
    bucket_70 = next(b for b in curve if b["range"] == "70-80")
    assert bucket_70["total"] == 3
    assert bucket_70["accepted"] == 2

    # Bucket 20-30 should have 2 entries
    bucket_20 = next(b for b in curve if b["range"] == "20-30")
    assert bucket_20["total"] == 2


# ── recommend_threshold ──────────────────────────────────────────────


def test_recommend_threshold_insufficient():
    entries = [_make_entry(70.0, True) for _ in range(10)]
    assert recommend_threshold(entries) is None


def test_recommend_threshold_with_data():
    # Create 60 entries: high confidence = accepted, low = rejected
    entries = []
    for i in range(30):
        entries.append(_make_entry(80.0 + i * 0.1, True))
    for i in range(30):
        entries.append(_make_entry(30.0 + i * 0.1, False))
    result = recommend_threshold(entries)
    assert result is not None
    # Should recommend something above the reject zone
    assert result > 30.0


# ── calibration_report ───────────────────────────────────────────────


def test_report_insufficient(tmp_path):
    entries = [_make_entry(70.0, True) for _ in range(5)]
    _write_log(tmp_path, entries)
    report = calibration_report(tmp_path)
    assert report["status"] == "insufficient"
    assert report["total_rated"] == 5


def test_report_preliminary(tmp_path):
    entries = [_make_entry(70.0 + i, True) for i in range(55)]
    _write_log(tmp_path, entries)
    report = calibration_report(tmp_path)
    assert report["status"] == "preliminary"
    assert report["total_rated"] == 55
    assert len(report["curve"]) == 10


def test_report_skip_rate(tmp_path):
    entries = [
        _make_entry(70.0, True),
        _make_entry(70.0, None),  # skip
        _make_entry(70.0, None),  # skip
    ]
    _write_log(tmp_path, entries)
    report = calibration_report(tmp_path)
    # 2 out of 3 are null → skip rate ≈ 0.667
    assert abs(report["skip_rate"] - 2 / 3) < 0.01
