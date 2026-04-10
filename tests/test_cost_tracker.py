"""Tests for provider cost tracker (OPT-06)."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from core.cognition.providers.cost_tracker import CostTracker, COST_LOG_FILE


@pytest.fixture
def tracker():
    return CostTracker()


@pytest.fixture
def custom_tracker():
    return CostTracker(rates={"test": {"input": 5.0, "output": 20.0}})


class TestEstimateCost:
    def test_local_is_free(self, tracker):
        assert tracker.estimate_cost("local", 1000, 500) == 0.0

    def test_cloud_provider_cost(self, tracker):
        # claude: $3/1M input, $15/1M output
        cost = tracker.estimate_cost("claude", 1_000_000, 1_000_000)
        assert cost == 18.0  # 3 + 15

    def test_small_query_cost(self, tracker):
        # 100 input + 50 output on openai ($2.5/1M in, $10/1M out)
        cost = tracker.estimate_cost("openai", 100, 50)
        assert abs(cost - 0.00075) < 0.00001  # 0.00025 + 0.0005

    def test_unknown_provider_defaults_to_free(self, tracker):
        assert tracker.estimate_cost("unknown_provider", 1000, 500) == 0.0

    def test_custom_rates(self, custom_tracker):
        cost = custom_tracker.estimate_cost("test", 1_000_000, 1_000_000)
        assert cost == 25.0


class TestLogQuery:
    def test_creates_log_file(self, tracker, tmp_path):
        log_dir = tmp_path / "costs"
        log_file = log_dir / "queries.jsonl"
        with patch("core.cognition.providers.cost_tracker.COST_LOG_DIR", log_dir), \
             patch("core.cognition.providers.cost_tracker.COST_LOG_FILE", log_file):
            tracker.log_query("local", "qwen2.5:14b", 100, 50, 250)

        assert log_file.exists()
        entry = json.loads(log_file.read_text().strip())
        assert entry["provider"] == "local"
        assert entry["model"] == "qwen2.5:14b"
        assert entry["input_tokens"] == 100
        assert entry["output_tokens"] == 50
        assert entry["latency_ms"] == 250
        assert entry["cost_usd"] == 0.0

    def test_appends_multiple_entries(self, tracker, tmp_path):
        log_dir = tmp_path / "costs"
        log_file = log_dir / "queries.jsonl"
        with patch("core.cognition.providers.cost_tracker.COST_LOG_DIR", log_dir), \
             patch("core.cognition.providers.cost_tracker.COST_LOG_FILE", log_file):
            tracker.log_query("local", "qwen2.5:14b", 100, 50, 200)
            tracker.log_query("claude", "claude-sonnet", 500, 200, 1500)

        lines = log_file.read_text().strip().split("\n")
        assert len(lines) == 2

    def test_auto_estimates_cost(self, tracker, tmp_path):
        log_dir = tmp_path / "costs"
        log_file = log_dir / "queries.jsonl"
        with patch("core.cognition.providers.cost_tracker.COST_LOG_DIR", log_dir), \
             patch("core.cognition.providers.cost_tracker.COST_LOG_FILE", log_file):
            tracker.log_query("claude", "sonnet", 1_000_000, 1_000_000, 2000)

        entry = json.loads(log_file.read_text().strip())
        assert entry["cost_usd"] == 18.0


class TestGetSummary:
    def test_empty_log(self, tracker, tmp_path):
        with patch("core.cognition.providers.cost_tracker.COST_LOG_FILE", tmp_path / "nope.jsonl"):
            assert tracker.get_summary() == {}

    def test_aggregates_by_provider(self, tracker, tmp_path):
        log_file = tmp_path / "queries.jsonl"
        from datetime import datetime
        now = datetime.now().isoformat()
        entries = [
            {"timestamp": now, "provider": "local", "input_tokens": 100, "output_tokens": 50, "cost_usd": 0.0},
            {"timestamp": now, "provider": "local", "input_tokens": 200, "output_tokens": 100, "cost_usd": 0.0},
            {"timestamp": now, "provider": "claude", "input_tokens": 500, "output_tokens": 200, "cost_usd": 0.0045},
        ]
        log_file.write_text("\n".join(json.dumps(e) for e in entries))

        with patch("core.cognition.providers.cost_tracker.COST_LOG_FILE", log_file):
            summary = tracker.get_summary()

        assert summary["local"]["queries"] == 2
        assert summary["local"]["input_tokens"] == 300
        assert summary["claude"]["queries"] == 1
