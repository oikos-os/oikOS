"""Tests for core/agency/budget.py — token budget tracker."""

from __future__ import annotations

import pytest

from core.agency.budget import BudgetStatus, TokenBudget


# ---------------------------------------------------------------------------
# Allocation
# ---------------------------------------------------------------------------

def test_allocate_file_management():
    b = TokenBudget.allocate("file_management")
    assert (b.max_input, b.max_output, b.max_tool_calls, b.max_retries) == (2000, 1000, 3, 1)


def test_allocate_vault_query():
    b = TokenBudget.allocate("vault_query")
    assert (b.max_input, b.max_output, b.max_tool_calls, b.max_retries) == (4000, 2000, 5, 2)


def test_allocate_research_web():
    b = TokenBudget.allocate("research_web")
    assert (b.max_input, b.max_output, b.max_tool_calls, b.max_retries) == (8000, 4000, 10, 3)


def test_allocate_browser_automation():
    b = TokenBudget.allocate("browser_automation")
    assert (b.max_input, b.max_output, b.max_tool_calls, b.max_retries) == (6000, 3000, 8, 2)


def test_allocate_unknown_raises():
    with pytest.raises(ValueError, match="Unknown action_type"):
        TokenBudget.allocate("teleportation")


# ---------------------------------------------------------------------------
# Consumption
# ---------------------------------------------------------------------------

def test_consume_input():
    b = TokenBudget.allocate("file_management")
    b.consume(500, "input")
    assert b.used_input == 500


def test_consume_output():
    b = TokenBudget.allocate("file_management")
    b.consume(300, "output")
    assert b.used_output == 300


def test_consume_accumulates():
    b = TokenBudget.allocate("file_management")
    b.consume(1000, "input")
    b.consume(500, "input")
    assert b.used_input == 1500


def test_consume_zero_noop():
    b = TokenBudget.allocate("file_management")
    b.consume(0, "input")
    assert b.used_input == 0


def test_consume_negative_raises():
    b = TokenBudget.allocate("file_management")
    with pytest.raises(ValueError):
        b.consume(-1, "input")


def test_consume_invalid_direction_raises():
    b = TokenBudget.allocate("file_management")
    with pytest.raises(ValueError, match="direction"):
        b.consume(100, "sideways")


# ---------------------------------------------------------------------------
# Tool Call / Retry Tracking
# ---------------------------------------------------------------------------

def test_record_tool_call():
    b = TokenBudget.allocate("file_management")
    b.record_tool_call()
    assert b.tool_calls == 1


def test_record_tool_call_accumulates():
    b = TokenBudget.allocate("file_management")
    b.record_tool_call()
    b.record_tool_call()
    b.record_tool_call()
    assert b.tool_calls == 3


def test_record_retry():
    b = TokenBudget.allocate("file_management")
    b.record_retry()
    assert b.retries == 1


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------

def test_status_high_at_start():
    b = TokenBudget.allocate("vault_query")
    assert b.check() == BudgetStatus.HIGH


def test_status_medium_at_50_pct():
    b = TokenBudget.allocate("vault_query")  # capacity = 6000
    b.consume(3000, "input")
    assert b.check() == BudgetStatus.MEDIUM


def test_status_low_at_75_pct():
    b = TokenBudget.allocate("vault_query")  # capacity = 6000
    b.consume(4000, "input")
    b.consume(500, "output")
    assert b.check() == BudgetStatus.LOW


def test_status_critical_at_90_pct():
    b = TokenBudget.allocate("vault_query")  # capacity = 6000
    b.consume(4000, "input")
    b.consume(1400, "output")
    assert b.check() == BudgetStatus.CRITICAL


def test_status_considers_both_directions():
    b = TokenBudget.allocate("file_management")  # capacity = 3000
    b.consume(750, "input")
    b.consume(750, "output")
    assert b.check() == BudgetStatus.MEDIUM
    assert b.total_used == 1500


# ---------------------------------------------------------------------------
# Circuit Breaker
# ---------------------------------------------------------------------------

def test_enforce_true_within_budget():
    b = TokenBudget.allocate("file_management")
    b.consume(100, "input")
    assert b.enforce() is True


def test_enforce_false_at_input_ceiling():
    b = TokenBudget.allocate("file_management")
    b.consume(2000, "input")
    assert b.enforce() is False


def test_enforce_false_at_output_ceiling():
    b = TokenBudget.allocate("file_management")
    b.consume(1000, "output")
    assert b.enforce() is False


def test_enforce_false_at_tool_call_ceiling():
    b = TokenBudget.allocate("file_management")
    for _ in range(3):
        b.record_tool_call()
    assert b.enforce() is False


def test_enforce_false_at_retry_ceiling():
    b = TokenBudget.allocate("file_management")
    b.record_retry()
    assert b.enforce() is False


# ---------------------------------------------------------------------------
# Prompt Injection
# ---------------------------------------------------------------------------

def test_format_injection_starts_with_budget():
    b = TokenBudget.allocate("file_management")
    assert b.format_injection().startswith("[BUDGET]")


def test_format_injection_contains_token_counts():
    b = TokenBudget.allocate("file_management")
    b.consume(500, "input")
    inj = b.format_injection()
    assert "500" in inj
    assert "3,000" in inj


def test_format_injection_contains_tool_calls():
    b = TokenBudget.allocate("file_management")
    b.record_tool_call()
    inj = b.format_injection()
    assert "1/3" in inj


def test_format_injection_contains_status():
    b = TokenBudget.allocate("file_management")
    inj = b.format_injection()
    assert "HIGH" in inj
    assert "0%" in inj
