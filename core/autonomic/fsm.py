"""Finite State Machine — lifecycle state persistence, transitions, callbacks."""

from __future__ import annotations

import json
import logging
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from core.interface.config import FSM_STATE_FILE, FSM_TRANSITION_LOG, VAULT_DIR
from core.interface.models import SystemState

log = logging.getLogger(__name__)

# ── Transition rules ─────────────────────────────────────────────────
# {current_state: set_of_valid_targets}
VALID_TRANSITIONS: dict[SystemState, set[SystemState]] = {
    SystemState.ACTIVE: {SystemState.IDLE, SystemState.ASLEEP},
    SystemState.IDLE: {SystemState.ACTIVE, SystemState.ASLEEP},
    SystemState.ASLEEP: {SystemState.ACTIVE},
}


def get_current_state() -> SystemState:
    """Load persisted state. Returns ACTIVE if file missing or corrupt."""
    try:
        if FSM_STATE_FILE.exists():
            data = json.loads(FSM_STATE_FILE.read_text(encoding="utf-8"))
            return SystemState(data["state"])
    except (json.JSONDecodeError, KeyError, ValueError):
        log.warning("Corrupt state file — defaulting to ACTIVE")
    return SystemState.ACTIVE


def _save_state(state: SystemState) -> None:
    """Persist state to JSON."""
    FSM_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "state": state.value,
        "last_transition": datetime.now(timezone.utc).isoformat(),
    }
    FSM_STATE_FILE.write_text(json.dumps(data), encoding="utf-8")


def _log_transition(from_state: SystemState, to_state: SystemState, trigger: str) -> None:
    """Append transition record to JSONL log."""
    FSM_TRANSITION_LOG.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "from": from_state.value,
        "to": to_state.value,
        "trigger": trigger,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    with open(FSM_TRANSITION_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")


def transition_to(target: SystemState, trigger: str = "manual") -> dict:
    """Validate and execute state transition. Returns callback results.

    Same-state transition = no-op (no callbacks, no log).
    Invalid transition raises ValueError.
    """
    current = get_current_state()

    # Same-state no-op
    if current == target:
        return {"transition": None, "reason": "already in target state"}

    # Validate
    if target not in VALID_TRANSITIONS.get(current, set()):
        raise ValueError(f"Invalid transition: {current.value} -> {target.value}")

    # Persist + log
    _save_state(target)
    _log_transition(current, target, trigger)

    try:
        from core.autonomic.events import emit_event
        emit_event("fsm", "transition", {"from": current.value, "to": target.value, "trigger": trigger})
    except Exception:
        pass

    # Fire callback
    callback_result = {}
    callbacks = {
        SystemState.IDLE: _on_enter_idle,
        SystemState.ACTIVE: _on_enter_active,
        SystemState.ASLEEP: _on_enter_asleep,
    }
    cb = callbacks.get(target)
    if cb:
        try:
            callback_result = cb()
        except Exception as e:
            log.warning("Callback for %s failed: %s", target.value, e)
            callback_result = {"callback_error": str(e)}

    return {
        "transition": f"{current.value} -> {target.value}",
        "trigger": trigger,
        **callback_result,
    }


def _on_enter_idle() -> dict:
    """IDLE entry: vault re-index, scanner (wired in 6b.3), git auto-commit."""
    result: dict = {}

    # 1. Vault re-index (incremental)
    try:
        from core.memory.indexer import index_vault

        stats = index_vault(full_rebuild=False)
        result["reindex"] = stats
    except Exception as e:
        log.warning("IDLE re-index failed: %s", e)
        result["reindex_error"] = str(e)

    # 2. Consolidation Agent
    try:
        from core.agency.consolidation import run_consolidation

        consol_result = run_consolidation()
        result["consolidation"] = consol_result
    except Exception as e:
        log.warning("Consolidation failed: %s", e)
        result["consolidation_error"] = str(e)

    # 3. Scanner
    try:
        from core.autonomic.scanner import check_activation_gate, run_scan

        gate = check_activation_gate()
        if gate["active"]:
            scan_result = run_scan()
            result["scanner"] = scan_result
        else:
            result["scanner_inactive"] = gate["reason"]
    except Exception as e:
        log.warning("Scanner failed: %s", e)
        result["scanner_error"] = str(e)

    # 3. Git auto-commit vault
    result["git"] = _auto_commit_vault()

    return result


def _on_enter_active() -> dict:
    """ACTIVE entry: signal briefing ready (delivery handled by CLI)."""
    return {"briefing_ready": True}


def _on_enter_asleep() -> dict:
    """ASLEEP entry: placeholder for flushing pending writes."""
    return {"flushed": True}


def _auto_commit_vault() -> dict:
    """Git auto-commit vault/ changes only. Non-fatal on failure."""
    try:
        # Check for vault changes
        result = subprocess.run(
            ["git", "status", "--porcelain", str(VAULT_DIR)],
            capture_output=True,
            text=True,
            cwd=VAULT_DIR.parent,
            timeout=10,
        )
        if result.returncode != 0 or not result.stdout.strip():
            return {"committed": False, "reason": "no vault changes"}

        # Parse changed files from porcelain output
        changed_files = []
        for line in result.stdout.rstrip("\n").split("\n"):
            if len(line) >= 4:
                # Porcelain format: XY filename (or XY -> newname for renames)
                parts = line[3:].strip().split(" -> ")
                filepath = parts[-1].strip()
                changed_files.append(filepath)

        if not changed_files:
            return {"committed": False, "reason": "no vault changes"}

        # Stage specific files
        subprocess.run(
            ["git", "add"] + changed_files,
            capture_output=True,
            text=True,
            cwd=VAULT_DIR.parent,
            timeout=10,
        )

        # Commit
        now = datetime.now(timezone.utc)
        msg = f"auto: vault sync on IDLE entry ({now.strftime('%Y-%m-%d %H:%M')} UTC)"
        commit_result = subprocess.run(
            ["git", "commit", "-m", msg],
            capture_output=True,
            text=True,
            cwd=VAULT_DIR.parent,
            timeout=10,
        )

        return {
            "committed": commit_result.returncode == 0,
            "files": changed_files,
            "message": msg,
        }
    except Exception as e:
        log.warning("Git auto-commit failed: %s", e)
        return {"committed": False, "error": str(e)}


def get_last_transition_time() -> str | None:
    """Return ISO timestamp of last state transition, or None."""
    try:
        if FSM_STATE_FILE.exists():
            data = json.loads(FSM_STATE_FILE.read_text(encoding="utf-8"))
            return data.get("last_transition")
    except (json.JSONDecodeError, KeyError):
        pass
    return None
