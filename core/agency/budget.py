from __future__ import annotations

import enum
import logging

from core.interface.config import BUDGET_STATUS_THRESHOLDS, BUDGET_TIERS

log = logging.getLogger(__name__)


class BudgetStatus(enum.Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    CRITICAL = "CRITICAL"


class TokenBudget:
    def __init__(self, action_type: str, max_input: int, max_output: int,
                 max_tool_calls: int, max_retries: int):
        self.action_type = action_type
        self.max_input = max_input
        self.max_output = max_output
        self.max_tool_calls = max_tool_calls
        self.max_retries = max_retries
        self.used_input = 0
        self.used_output = 0
        self.tool_calls = 0
        self.retries = 0

    @classmethod
    def allocate(cls, action_type: str) -> TokenBudget:
        if action_type not in BUDGET_TIERS:
            raise ValueError(f"Unknown action_type: {action_type!r}")
        return cls(action_type, **BUDGET_TIERS[action_type])

    def consume(self, tokens: int, direction: str) -> None:
        if tokens < 0:
            raise ValueError("tokens must be non-negative")
        if direction not in ("input", "output"):
            raise ValueError(f"Invalid direction: {direction!r}")
        if direction == "input":
            self.used_input += tokens
        else:
            self.used_output += tokens

    def record_tool_call(self) -> None:
        self.tool_calls += 1

    def record_retry(self) -> None:
        self.retries += 1

    @property
    def total_capacity(self) -> int:
        return self.max_input + self.max_output

    @property
    def total_used(self) -> int:
        return self.used_input + self.used_output

    @property
    def utilization(self) -> float:
        return self.total_used / self.total_capacity if self.total_capacity else 0.0

    def check(self) -> BudgetStatus:
        u = self.utilization
        if u >= BUDGET_STATUS_THRESHOLDS["CRITICAL"]:
            return BudgetStatus.CRITICAL
        if u >= BUDGET_STATUS_THRESHOLDS["LOW"]:
            return BudgetStatus.LOW
        if u >= BUDGET_STATUS_THRESHOLDS["MEDIUM"]:
            return BudgetStatus.MEDIUM
        return BudgetStatus.HIGH

    def enforce(self) -> bool:
        return (self.used_input < self.max_input
                and self.used_output < self.max_output
                and self.tool_calls < self.max_tool_calls
                and self.retries < self.max_retries)

    def format_injection(self) -> str:
        pct = int(self.utilization * 100)
        return (
            f"[BUDGET] Used: {self.total_used:,}/{self.total_capacity:,} tokens ({pct}%). "
            f"Tool calls: {self.tool_calls}/{self.max_tool_calls}. "
            f"Status: {self.check().value}."
        )
