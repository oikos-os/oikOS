"""Onboarding state tracking — persists via settings.json."""
from __future__ import annotations

from core.interface.settings import get_setting, update_setting


def is_onboarding_complete() -> bool:
    try:
        return bool(get_setting("onboarding_complete"))
    except (KeyError, TypeError):
        return False


def mark_onboarding_complete() -> None:
    update_setting("onboarding_complete", True)
    update_setting("onboarding_step", 5)


def get_step() -> int:
    try:
        return int(get_setting("onboarding_step"))
    except (KeyError, TypeError, ValueError):
        return 0


def advance_step() -> int:
    step = get_step() + 1
    update_setting("onboarding_step", step)
    return step


def set_step(step: int) -> None:
    update_setting("onboarding_step", step)
