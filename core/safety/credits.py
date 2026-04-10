"""JSON file-based credit tracker with deficit spending."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from core.interface.config import CLOUD_HARD_CEILING_MULTIPLIER, CREDITS_FILE
from core.interface.models import CreditBalance

log = logging.getLogger(__name__)

_DEFAULT_DATA = {
    "used": 0,
    "last_reset": datetime.now(timezone.utc).replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat(),
    "log": [],
}


def _get_monthly_cap() -> int:
    """Read monthly cap from settings registry (hot-reloadable)."""
    from core.interface.settings import get_setting
    return int(get_setting("credits_monthly_cap"))


def _read_raw() -> dict:
    if not CREDITS_FILE.exists():
        _write_raw(_DEFAULT_DATA.copy())
    return json.loads(CREDITS_FILE.read_text(encoding="utf-8"))


def _write_raw(data: dict) -> None:
    CREDITS_FILE.parent.mkdir(parents=True, exist_ok=True)
    CREDITS_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def load_credits() -> CreditBalance:
    """Load current credit balance. Creates default file if missing."""
    data = _read_raw()
    used = data["used"]
    cap = _get_monthly_cap()
    remaining = max(0, cap - used)
    deficit = max(0, used - cap)
    return CreditBalance(
        monthly_cap=cap,
        used=used,
        remaining=remaining,
        in_deficit=used > cap,
        deficit=deficit,
        last_reset=data["last_reset"],
    )


def charge(amount: int, description: str) -> CreditBalance:
    """Charge credits. Allows deficit spending with logged warning."""
    reset_if_due()
    data = _read_raw()
    data["used"] += amount

    cap = _get_monthly_cap()
    if data["used"] > cap:
        log.warning("[DEFICIT DETECTED: COGNITIVE OVERRUN] used=%d cap=%d", data["used"], cap)

    data["log"].append({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "amount": amount,
        "description": description,
        "balance_after": max(0, cap - data["used"]),
    })

    _write_raw(data)
    return load_credits()


def reset_if_due() -> bool:
    """Reset credits if current month differs from last_reset month."""
    data = _read_raw()
    last = datetime.fromisoformat(data["last_reset"])
    now = datetime.now(timezone.utc)

    if now.year != last.year or now.month != last.month:
        data["used"] = 0
        data["last_reset"] = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()
        data["log"] = []
        _write_raw(data)
        log.info("Monthly credit reset applied.")
        return True
    return False


def check_hard_ceiling(amount: int = 0) -> bool:
    """Return True if projected usage would exceed hard ceiling (2x cap)."""
    data = _read_raw()
    hard_ceiling = _get_monthly_cap() * CLOUD_HARD_CEILING_MULTIPLIER
    return (data["used"] + amount) > hard_ceiling
