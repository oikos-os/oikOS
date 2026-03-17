"""Tests for the credit tracker."""

import json
from datetime import datetime, timezone
from unittest.mock import patch

from core.safety.credits import charge, load_credits, reset_if_due


def test_load_credits_creates_default(tmp_path):
    from core.interface.config import CREDITS_MONTHLY_CAP
    cred_file = tmp_path / "credits.json"
    with patch("core.safety.credits.CREDITS_FILE", cred_file):
        balance = load_credits()

    assert cred_file.exists()
    assert balance.monthly_cap == CREDITS_MONTHLY_CAP
    assert balance.used == 0
    assert balance.remaining == CREDITS_MONTHLY_CAP
    assert balance.in_deficit is False


def test_load_credits_reads_existing(tmp_path):
    cred_file = tmp_path / "credits.json"
    cred_file.write_text(json.dumps({
        "monthly_cap": 500,
        "used": 200,
        "last_reset": "2026-02-01T00:00:00+00:00",
        "log": [],
    }), encoding="utf-8")

    with patch("core.safety.credits.CREDITS_FILE", cred_file):
        balance = load_credits()

    assert balance.monthly_cap == 500
    assert balance.used == 200
    assert balance.remaining == 300


def test_charge_deducts(tmp_path):
    cred_file = tmp_path / "credits.json"
    cred_file.write_text(json.dumps({
        "monthly_cap": 1000,
        "used": 0,
        "last_reset": datetime.now(timezone.utc).replace(day=1).isoformat(),
        "log": [],
    }), encoding="utf-8")

    with patch("core.safety.credits.CREDITS_FILE", cred_file):
        balance = charge(50, "test query")

    assert balance.used == 50
    assert balance.remaining == 950


def test_charge_deficit_spending(tmp_path):
    cred_file = tmp_path / "credits.json"
    cred_file.write_text(json.dumps({
        "monthly_cap": 100,
        "used": 95,
        "last_reset": datetime.now(timezone.utc).replace(day=1).isoformat(),
        "log": [],
    }), encoding="utf-8")

    with patch("core.safety.credits.CREDITS_FILE", cred_file):
        balance = charge(20, "expensive query")

    assert balance.used == 115
    assert balance.in_deficit is True
    assert balance.deficit == 15
    assert balance.remaining == 0


def test_reset_if_due_same_month(tmp_path):
    cred_file = tmp_path / "credits.json"
    now = datetime.now(timezone.utc)
    cred_file.write_text(json.dumps({
        "monthly_cap": 1000,
        "used": 500,
        "last_reset": now.replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat(),
        "log": [],
    }), encoding="utf-8")

    with patch("core.safety.credits.CREDITS_FILE", cred_file):
        assert reset_if_due() is False


def test_check_hard_ceiling_below(tmp_path):
    from core.safety.credits import check_hard_ceiling

    cred_file = tmp_path / "credits.json"
    cred_file.write_text(json.dumps({
        "monthly_cap": 1000,
        "used": 500,
        "last_reset": datetime.now(timezone.utc).replace(day=1).isoformat(),
        "log": [],
    }), encoding="utf-8")

    with patch("core.safety.credits.CREDITS_FILE", cred_file):
        assert check_hard_ceiling() is False  # 500 < 2000


def test_check_hard_ceiling_exceeded(tmp_path):
    from core.safety.credits import check_hard_ceiling

    cred_file = tmp_path / "credits.json"
    cred_file.write_text(json.dumps({
        "monthly_cap": 1000,
        "used": 2001,
        "last_reset": datetime.now(timezone.utc).replace(day=1).isoformat(),
        "log": [],
    }), encoding="utf-8")

    with patch("core.safety.credits.CREDITS_FILE", cred_file):
        assert check_hard_ceiling() is True  # 2001 > 2000


def test_reset_if_due_new_month(tmp_path):
    cred_file = tmp_path / "credits.json"
    cred_file.write_text(json.dumps({
        "monthly_cap": 1000,
        "used": 800,
        "last_reset": "2025-12-01T00:00:00+00:00",
        "log": [{"amount": 800}],
    }), encoding="utf-8")

    with patch("core.safety.credits.CREDITS_FILE", cred_file):
        assert reset_if_due() is True
        balance = load_credits()

    assert balance.used == 0
