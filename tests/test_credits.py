"""Tests for the credit tracker."""

import json
from datetime import datetime, timezone
from unittest.mock import patch

from core.safety.credits import charge, load_credits, reset_if_due

# All tests patch _get_monthly_cap since credits.py now reads cap from the
# settings registry, not from the JSON file.

_CAP = "core.safety.credits._get_monthly_cap"


def _write_credits(cred_file, *, used=0, last_reset=None, log=None):
    """Write a credits JSON file with usage data (cap is in registry now)."""
    if last_reset is None:
        last_reset = datetime.now(timezone.utc).replace(day=1).isoformat()
    cred_file.write_text(json.dumps({
        "used": used,
        "last_reset": last_reset,
        "log": log or [],
    }), encoding="utf-8")


def test_load_credits_creates_default(tmp_path):
    cred_file = tmp_path / "credits.json"
    with patch("core.safety.credits.CREDITS_FILE", cred_file), \
         patch(_CAP, return_value=1000000):
        balance = load_credits()

    assert cred_file.exists()
    assert balance.monthly_cap == 1000000
    assert balance.used == 0
    assert balance.remaining == 1000000
    assert balance.in_deficit is False


def test_load_credits_reads_existing(tmp_path):
    cred_file = tmp_path / "credits.json"
    _write_credits(cred_file, used=200, last_reset="2026-02-01T00:00:00+00:00")

    with patch("core.safety.credits.CREDITS_FILE", cred_file), \
         patch(_CAP, return_value=500):
        balance = load_credits()

    assert balance.monthly_cap == 500
    assert balance.used == 200
    assert balance.remaining == 300


def test_charge_deducts(tmp_path):
    cred_file = tmp_path / "credits.json"
    _write_credits(cred_file, used=0)

    with patch("core.safety.credits.CREDITS_FILE", cred_file), \
         patch(_CAP, return_value=1000):
        balance = charge(50, "test query")

    assert balance.used == 50
    assert balance.remaining == 950


def test_charge_deficit_spending(tmp_path):
    cred_file = tmp_path / "credits.json"
    _write_credits(cred_file, used=95)

    with patch("core.safety.credits.CREDITS_FILE", cred_file), \
         patch(_CAP, return_value=100):
        balance = charge(20, "expensive query")

    assert balance.used == 115
    assert balance.in_deficit is True
    assert balance.deficit == 15
    assert balance.remaining == 0


def test_reset_if_due_same_month(tmp_path):
    cred_file = tmp_path / "credits.json"
    now = datetime.now(timezone.utc)
    _write_credits(cred_file, used=500,
                   last_reset=now.replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat())

    with patch("core.safety.credits.CREDITS_FILE", cred_file):
        assert reset_if_due() is False


def test_check_hard_ceiling_below(tmp_path):
    from core.safety.credits import check_hard_ceiling

    cred_file = tmp_path / "credits.json"
    _write_credits(cred_file, used=500)

    with patch("core.safety.credits.CREDITS_FILE", cred_file), \
         patch(_CAP, return_value=1000):
        assert check_hard_ceiling() is False  # 500 < 2000


def test_check_hard_ceiling_exceeded(tmp_path):
    from core.safety.credits import check_hard_ceiling

    cred_file = tmp_path / "credits.json"
    _write_credits(cred_file, used=2001)

    with patch("core.safety.credits.CREDITS_FILE", cred_file), \
         patch(_CAP, return_value=1000):
        assert check_hard_ceiling() is True  # 2001 > 2000


def test_reset_if_due_new_month(tmp_path):
    cred_file = tmp_path / "credits.json"
    _write_credits(cred_file, used=800, last_reset="2025-12-01T00:00:00+00:00",
                   log=[{"amount": 800}])

    with patch("core.safety.credits.CREDITS_FILE", cred_file), \
         patch(_CAP, return_value=1000):
        assert reset_if_due() is True
        balance = load_credits()

    assert balance.used == 0


# ── T-117: Credits cap roundtrip + hot-reload ──────────────────────────


def test_credits_cap_roundtrip(tmp_path):
    """Changing credits_monthly_cap setting affects credit enforcement."""
    cred_file = tmp_path / "credits.json"
    _write_credits(cred_file, used=600)

    # Cap at 1000 → not in deficit
    with patch("core.safety.credits.CREDITS_FILE", cred_file), \
         patch(_CAP, return_value=1000):
        balance = load_credits()
    assert balance.remaining == 400
    assert balance.in_deficit is False

    # Cap lowered to 500 → now in deficit
    with patch("core.safety.credits.CREDITS_FILE", cred_file), \
         patch(_CAP, return_value=500):
        balance = load_credits()
    assert balance.remaining == 0
    assert balance.in_deficit is True
    assert balance.deficit == 100


def test_credits_cap_hot_reload_mid_session(tmp_path):
    """Changing cap mid-session affects the next charge."""
    cred_file = tmp_path / "credits.json"
    _write_credits(cred_file, used=0)

    with patch("core.safety.credits.CREDITS_FILE", cred_file), \
         patch(_CAP, return_value=1000):
        # First charge under 1000 cap
        b1 = charge(800, "first query")
        assert b1.remaining == 200
        assert b1.in_deficit is False

    # Cap lowered to 500 mid-session → next charge sees new cap
    with patch("core.safety.credits.CREDITS_FILE", cred_file), \
         patch(_CAP, return_value=500):
        b2 = charge(50, "second query")
        assert b2.used == 850
        assert b2.in_deficit is True
        assert b2.deficit == 350
