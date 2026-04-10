"""Confidence threshold calibration from routing log feedback data."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from core.interface.config import ROUTING_CONFIDENCE_THRESHOLD, ROUTING_LOG_DIR

log = logging.getLogger(__name__)

MIN_SAMPLES_PRELIMINARY = 50
MIN_SAMPLES_STABLE = 200


def load_rated_entries(log_dir: Path | None = None) -> list[dict]:
    """Load all routing log entries where user_accepted is not null."""
    log_dir = log_dir or ROUTING_LOG_DIR
    if not log_dir.exists():
        return []

    entries = []
    for log_file in sorted(log_dir.glob("*.jsonl")):
        for line in log_file.read_text(encoding="utf-8").strip().split("\n"):
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if entry.get("user_accepted") is not None and entry.get("confidence_score") is not None:
                entries.append(entry)

    return entries


def compute_accuracy_curve(entries: list[dict], buckets: int = 10) -> list[dict]:
    """Compute accuracy at each confidence bucket.

    Returns list of {threshold, total, accepted, accuracy} dicts.
    """
    bucket_size = 100.0 / buckets
    curve = []

    for i in range(buckets):
        low = i * bucket_size
        high = (i + 1) * bucket_size

        bucket_entries = [
            e for e in entries
            if low <= e["confidence_score"] < high
        ]

        total = len(bucket_entries)
        accepted = sum(1 for e in bucket_entries if e["user_accepted"] is True)
        accuracy = accepted / total if total > 0 else None

        curve.append({
            "range": f"{low:.0f}-{high:.0f}",
            "total": total,
            "accepted": accepted,
            "accuracy": accuracy,
        })

    return curve


def recommend_threshold(entries: list[dict], target_accuracy: float = 0.8) -> float | None:
    """Find the lowest confidence score where accuracy >= target_accuracy.

    Uses a sweep from high to low confidence. Returns the threshold where
    cumulative accuracy at-or-above that threshold meets the target.
    Returns None if insufficient data.
    """
    if len(entries) < MIN_SAMPLES_PRELIMINARY:
        return None

    # Sort entries by confidence descending
    sorted_entries = sorted(entries, key=lambda e: e["confidence_score"], reverse=True)

    # Sweep from high confidence down
    accepted_count = 0
    total_count = 0

    for entry in sorted_entries:
        total_count += 1
        if entry["user_accepted"] is True:
            accepted_count += 1

        cumulative_accuracy = accepted_count / total_count
        if cumulative_accuracy >= target_accuracy and total_count >= 10:
            # This confidence score is the lowest where accuracy holds
            return entry["confidence_score"]

    # If we never hit the target, return the current threshold
    return ROUTING_CONFIDENCE_THRESHOLD


def calibration_report(log_dir: Path | None = None) -> dict:
    """Generate a full calibration report.

    Returns:
        {
            "total_rated": int,
            "status": "insufficient" | "preliminary" | "stable",
            "curve": [...],
            "recommended_threshold": float | None,
            "current_threshold": float,
            "skip_rate": float,
        }
    """
    log_dir = log_dir or ROUTING_LOG_DIR
    entries = load_rated_entries(log_dir)

    # Also count total entries (including unrated) for skip rate
    all_entries = []
    if log_dir.exists():
        for log_file in sorted(log_dir.glob("*.jsonl")):
            for line in log_file.read_text(encoding="utf-8").strip().split("\n"):
                if not line.strip():
                    continue
                try:
                    all_entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue

    total_all = len(all_entries)
    total_rated = len(entries)
    total_skipped = sum(1 for e in all_entries if e.get("user_accepted") is None)
    skip_rate = total_skipped / total_all if total_all > 0 else 0.0

    if total_rated < MIN_SAMPLES_PRELIMINARY:
        return {
            "total_rated": total_rated,
            "total_queries": total_all,
            "status": "insufficient",
            "min_required": MIN_SAMPLES_PRELIMINARY,
            "curve": [],
            "recommended_threshold": None,
            "current_threshold": ROUTING_CONFIDENCE_THRESHOLD,
            "skip_rate": skip_rate,
        }

    status = "stable" if total_rated >= MIN_SAMPLES_STABLE else "preliminary"
    curve = compute_accuracy_curve(entries)
    recommended = recommend_threshold(entries)

    return {
        "total_rated": total_rated,
        "total_queries": total_all,
        "status": status,
        "curve": curve,
        "recommended_threshold": recommended,
        "current_threshold": ROUTING_CONFIDENCE_THRESHOLD,
        "skip_rate": skip_rate,
    }
