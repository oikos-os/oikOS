"""Provider cost tracker — per-query cost estimation and JSONL logging (OPT-06)."""

from __future__ import annotations

import json
import logging
from datetime import date, datetime
from pathlib import Path
from typing import Any

from core.interface.config import PROJECT_ROOT

log = logging.getLogger(__name__)

COST_LOG_DIR = PROJECT_ROOT / "logs" / "costs"
COST_LOG_FILE = COST_LOG_DIR / "queries.jsonl"

# Default cost rates (USD per 1M tokens). Overridden by providers.toml [costs].
_DEFAULT_RATES: dict[str, dict[str, float]] = {
    "local": {"input": 0.0, "output": 0.0},
    "ollama": {"input": 0.0, "output": 0.0},
    "claude": {"input": 3.0, "output": 15.0},
    "anthropic": {"input": 3.0, "output": 15.0},
    "gemini": {"input": 1.25, "output": 5.0},
    "openai": {"input": 2.5, "output": 10.0},
    "litellm": {"input": 2.5, "output": 10.0},
}


class CostTracker:
    """Tracks per-query inference costs in a JSONL log."""

    def __init__(self, rates: dict[str, dict[str, float]] | None = None):
        self._rates = rates or _DEFAULT_RATES

    def estimate_cost(self, provider: str, input_tokens: int, output_tokens: int) -> float:
        """Estimate cost in USD for a query."""
        rate = self._rates.get(provider, self._rates.get("local", {}))
        input_rate = rate.get("input", 0.0) / 1_000_000
        output_rate = rate.get("output", 0.0) / 1_000_000
        return input_tokens * input_rate + output_tokens * output_rate

    def log_query(
        self,
        provider: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        latency_ms: int,
        cost_usd: float | None = None,
    ) -> None:
        """Append a query record to the JSONL cost log."""
        if cost_usd is None:
            cost_usd = self.estimate_cost(provider, input_tokens, output_tokens)

        entry = {
            "timestamp": datetime.now().isoformat(),
            "provider": provider,
            "model": model,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "latency_ms": latency_ms,
            "cost_usd": round(cost_usd, 6),
        }

        try:
            COST_LOG_DIR.mkdir(parents=True, exist_ok=True)
            with COST_LOG_FILE.open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry) + "\n")
        except OSError as exc:
            log.warning("Failed to write cost log: %s", exc)

    def get_summary(self, days: int = 30) -> dict[str, Any]:
        """Aggregate cost data by provider for the last N days."""
        if not COST_LOG_FILE.exists():
            return {}

        from datetime import timedelta
        cutoff_date = (date.today() - timedelta(days=days)).isoformat()

        totals: dict[str, dict[str, Any]] = {}
        for line in COST_LOG_FILE.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue

            ts = entry.get("timestamp", "")[:10]
            if ts < cutoff_date:
                continue

            provider = entry.get("provider", "unknown")
            if provider not in totals:
                totals[provider] = {"queries": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}

            totals[provider]["queries"] += 1
            totals[provider]["input_tokens"] += entry.get("input_tokens", 0)
            totals[provider]["output_tokens"] += entry.get("output_tokens", 0)
            totals[provider]["cost_usd"] += entry.get("cost_usd", 0.0)

        return totals
