"""OS Daemon — heartbeat loop, local inference management, service install,
vault file watcher, session auto-close, budget alerts, prewarming, log rotation."""

from __future__ import annotations

import asyncio
import ctypes
import ctypes.wintypes
import json
import logging
import os
import signal
import subprocess
import sys
import time
from contextlib import contextmanager
from datetime import datetime, timezone

from core.interface.config import (
    DAEMON_BUDGET_ALERT_THRESHOLD,
    DAEMON_BUDGET_CHECK_INTERVAL_SEC,
    DAEMON_BUDGET_CRITICAL_THRESHOLD,
    DAEMON_HEARTBEAT_INTERVAL_SEC,
    DAEMON_LOG_FILE,
    DAEMON_LOG_ROTATION_INTERVAL_SEC,
    DAEMON_LOG_ROTATION_KEEP_LINES,
    DAEMON_LOG_ROTATION_MAX_BYTES,
    DAEMON_PID_FILE,
    DAEMON_STOP_FILE,
    DAEMON_PREWARM_DATA_FILE,
    DAEMON_PREWARM_LEAD_MINUTES,
    DAEMON_PREWARM_MIN_SAMPLES,
    DAEMON_SESSION_CHECK_INTERVAL_SEC,
    DAEMON_SESSION_STALE_MINUTES,
    DAEMON_VAULT_WATCH_DIRS,
    INFERENCE_MODEL,
    PROJECT_ROOT,
)
from core.autonomic.inference_manager import OllamaManager
from core.cognition.providers.config_loader import load_providers_config

log = logging.getLogger(__name__)

# ── Module State ──────────────────────────────────────────────────────
_running: bool = False
_inference_active: bool = False  # Deprecated: kept for handler.py compat
_start_time: float = 0.0
_inference_manager: OllamaManager | None = None
_restart_attempts: int = 0
_restart_window_start: float | None = None

MAX_RESTART_ATTEMPTS = 3
RESTART_WINDOW_SECONDS = 1800  # 30 minutes
RESTART_BACKOFF = [5, 15, 45]  # seconds

# Interval trackers for new features
_last_vault_mtime: float = 0.0
_last_session_check: float = 0.0
_last_budget_check: float = 0.0
_budget_alert_fired: bool = False
_budget_critical_fired: bool = False
_last_log_rotation: float = 0.0
_last_prewarm_check: float = 0.0
_today_activity_logged: bool = False
_session_warning_session_id: str | None = None  # keyed on session_id to auto-reset across sessions


# ── Inference Guard (deprecated — kept for handler.py compat) ────────
@contextmanager
def inference_active():
    """Context manager — no-op guard kept for backward compatibility."""
    global _inference_active
    _inference_active = True
    try:
        yield
    finally:
        _inference_active = False


# ── Windows Input Idle ────────────────────────────────────────────────
class _LASTINPUTINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", ctypes.wintypes.UINT),
        ("dwTime", ctypes.wintypes.DWORD),
    ]


def _get_idle_seconds() -> float:
    """Seconds since last keyboard/mouse input (Windows only)."""
    lii = _LASTINPUTINFO()
    lii.cbSize = ctypes.sizeof(lii)
    ctypes.windll.user32.GetLastInputInfo(ctypes.byref(lii))
    millis = ctypes.windll.kernel32.GetTickCount() - lii.dwTime
    return millis / 1000.0


# ── Original Checks ──────────────────────────────────────────────────
def _check_input_activity() -> None:
    """IDLE timer via GetLastInputInfo. Transitions ACTIVE<->IDLE."""
    global _today_activity_logged

    from core.autonomic.fsm import get_current_state, transition_to
    from core.interface.models import SystemState

    idle_secs = _get_idle_seconds()
    from core.interface.settings import get_setting
    threshold = get_setting("idle_timeout") * 60
    current = get_current_state()

    if idle_secs > threshold and current == SystemState.ACTIVE:
        transition_to(SystemState.IDLE, trigger="daemon:inactivity")
        log.info("ACTIVE -> IDLE (idle %.0fs)", idle_secs)
    elif idle_secs < threshold and current == SystemState.IDLE:
        transition_to(SystemState.ACTIVE, trigger="daemon:activity")
        log.info("IDLE -> ACTIVE (activity detected)")

    # Track first activity of the day for prewarming
    if idle_secs < 60 and not _today_activity_logged:
        _record_daily_activity()
        _today_activity_logged = True


# ── Local Inference Management ───────────────────────────────────────

_CLOUD_PROVIDER_TYPES = {"gemini", "anthropic", "anthropic-oauth", "litellm"}


def _default_provider_is_cloud() -> bool:
    """Quick check: is the configured default provider a cloud type?"""
    try:
        config = load_providers_config()
        default_name = config.get("general", {}).get("default", "local")
        providers = config.get("providers", {})
        default_prov = providers.get(default_name, {})
        return default_prov.get("type", "") in _CLOUD_PROVIDER_TYPES
    except Exception:
        return False


def _init_inference_manager() -> OllamaManager | None:
    """Instantiate manager based on providers.toml. Returns None if no local backend."""
    if _default_provider_is_cloud():
        log.debug("Default provider is cloud — skipping local inference management")
        return None
    try:
        mgr = OllamaManager()
        mgr.reload_config()
        if mgr.should_run():
            return mgr
        return None
    except Exception:
        log.warning("Failed to initialize inference manager")
        return None


def _check_local_inference() -> None:
    """Manage local inference lifecycle. Called from heartbeat."""
    global _inference_manager
    if _inference_manager is None:
        # Config may have changed — maybe a local backend was added
        _inference_manager = _init_inference_manager()
        if _inference_manager is None:
            return

    if _inference_manager.check_config_changed():
        _inference_manager.reload_config()

    if not _inference_manager.should_run():
        # Was needed, now isn't (e.g. user switched to cloud)
        log.info("Local inference no longer needed — disabling management")
        _inference_manager = None
        return

    if _inference_manager.is_intentional_stop():
        return

    try:
        healthy = asyncio.run(_inference_manager.health_check())
    except Exception:
        healthy = False

    if not healthy:
        _attempt_restart()


def _attempt_restart() -> None:
    """Restart local inference with backoff. Transitions to IDLE on exhaustion."""
    global _restart_attempts, _restart_window_start

    now = time.time()

    if (_restart_window_start is None or
            now - _restart_window_start > RESTART_WINDOW_SECONDS):
        _restart_attempts = 0
        _restart_window_start = now

    if _restart_attempts >= MAX_RESTART_ATTEMPTS:
        name = _inference_manager.backend_name()
        log.warning("%s unrecoverable after %d attempts. Cloud fallback active.",
                    name, MAX_RESTART_ATTEMPTS)
        from core.autonomic.fsm import transition_to
        from core.interface.models import SystemState
        from core.autonomic.events import emit_event
        transition_to(SystemState.IDLE, trigger=f"daemon:{name.lower()}_exhausted")
        emit_event("daemon", "restart_exhausted", {
            "backend": name,
            "attempts": MAX_RESTART_ATTEMPTS,
        })
        return

    backoff = RESTART_BACKOFF[min(_restart_attempts, len(RESTART_BACKOFF) - 1)]
    name = _inference_manager.backend_name()
    log.info("Restarting %s (attempt %d/%d, backoff %ds)",
             name, _restart_attempts + 1, MAX_RESTART_ATTEMPTS, backoff)

    # T-119: emit notification event (SHOULD tier with escalation at threshold=2)
    try:
        from core.autonomic.events import emit_event
        emit_event("inference", "restart_attempt", {
            "backend": name,
            "attempt": _restart_attempts + 1,
            "max_attempts": MAX_RESTART_ATTEMPTS,
        })
    except Exception as e:
        log.debug("restart_attempt emit suppressed: %s", e)

    time.sleep(backoff)
    try:
        success = asyncio.run(_inference_manager.restart())
    except Exception:
        success = False
    _restart_attempts += 1

    if success:
        log.info("%s restarted successfully.", name)
        _restart_attempts = 0
        _restart_window_start = None


# ── Feature 1: Vault File Watcher ────────────────────────────────────
def _check_vault_changes() -> None:
    """Poll vault directories for file changes. Trigger incremental index."""
    global _last_vault_mtime

    latest_mtime = 0.0
    for watch_dir in DAEMON_VAULT_WATCH_DIRS:
        if not watch_dir.exists():
            continue
        for f in watch_dir.rglob("*.md"):
            try:
                mt = f.stat().st_mtime
                if mt > latest_mtime:
                    latest_mtime = mt
            except OSError:
                continue

    if _last_vault_mtime == 0.0:
        _last_vault_mtime = latest_mtime
        return

    if latest_mtime > _last_vault_mtime:
        _last_vault_mtime = latest_mtime
        log.info("Vault change detected — triggering incremental index")
        try:
            from core.memory.indexer import index_vault

            stats = index_vault(full_rebuild=False)
            log.info("Auto-index: added=%d skipped=%d deleted=%d", stats["added"], stats["skipped"], stats["deleted"])

            from core.autonomic.events import emit_event
            emit_event("daemon", "vault_reindex", {
                "trigger": "file_watcher",
                "added": stats["added"],
                "skipped": stats["skipped"],
                "deleted": stats["deleted"],
            })
        except Exception as e:
            log.warning("Auto-index failed: %s", e)


# ── Feature 2: Session Auto-Close ────────────────────────────────────
def _check_stale_sessions() -> None:
    """Close web UI sessions that have been inactive too long.

    Also emits daemon.session_warning 5 minutes before the auto-close threshold
    (T-119) so the user can prevent losing their session.
    """
    global _last_session_check, _session_warning_session_id

    now = time.monotonic()
    if now - _last_session_check < DAEMON_SESSION_CHECK_INTERVAL_SEC:
        return
    _last_session_check = now

    try:
        from core.memory.session import SESSION_STATE_FILE, _load_state, close_session

        state = _load_state()
        if state is None:
            _session_warning_session_id = None
            return

        current_session_id = state.get("session_id", "")
        last_active = datetime.fromisoformat(state["last_active_at"])
        elapsed_min = (datetime.now(timezone.utc) - last_active).total_seconds() / 60

        # T-119: emit warning 5 minutes before stale threshold.
        # Keyed on session_id so a replaced session (via get_or_create_session)
        # automatically gets its own warning — no flag leak across sessions.
        warning_threshold = DAEMON_SESSION_STALE_MINUTES - 5
        if (_session_warning_session_id != current_session_id
                and warning_threshold <= elapsed_min < DAEMON_SESSION_STALE_MINUTES):
            _session_warning_session_id = current_session_id
            minutes_remaining = max(1, round(DAEMON_SESSION_STALE_MINUTES - elapsed_min))
            try:
                from core.autonomic.events import emit_event
                emit_event("daemon", "session_warning", {
                    "session_id": current_session_id,
                    "minutes_remaining": minutes_remaining,
                    "elapsed_minutes": round(elapsed_min),
                })
            except Exception as e:
                log.debug("session_warning emit suppressed: %s", e)
            log.info(
                "Session closing warning emitted (session=%s, %d min remaining)",
                current_session_id, minutes_remaining,
            )

        if elapsed_min > DAEMON_SESSION_STALE_MINUTES:
            result = close_session()
            if result:
                log.info(
                    "Auto-closed stale session %s (inactive %.0f min, %d interactions)",
                    result["session_id"], elapsed_min, result.get("interaction_count", 0),
                )
                _session_warning_session_id = None
                from core.autonomic.events import emit_event
                emit_event("daemon", "session_auto_close", {
                    "session_id": result["session_id"],
                    "inactive_minutes": round(elapsed_min),
                    "interaction_count": result.get("interaction_count", 0),
                })
    except Exception as e:
        log.warning("Session auto-close check failed: %s", e)


# ── Feature 3: Cloud Budget Alerts ───────────────────────────────────
def _check_budget_alerts() -> None:
    """Emit events when credit usage exceeds alert thresholds."""
    global _last_budget_check, _budget_alert_fired, _budget_critical_fired

    now = time.monotonic()
    if now - _last_budget_check < DAEMON_BUDGET_CHECK_INTERVAL_SEC:
        return
    _last_budget_check = now

    try:
        from core.safety.credits import load_credits
        from core.autonomic.events import emit_event

        balance = load_credits()
        if balance.monthly_cap <= 0:
            return

        usage_ratio = balance.used / balance.monthly_cap

        if usage_ratio >= DAEMON_BUDGET_CRITICAL_THRESHOLD and not _budget_critical_fired:
            _budget_critical_fired = True
            emit_event("daemon", "budget_critical", {
                "used": balance.used,
                "cap": balance.monthly_cap,
                "usage_percent": round(usage_ratio * 100),
                "message": f"CRITICAL: Cloud budget at {usage_ratio:.0%} — {balance.remaining} credits remaining",
            })
            log.warning("Budget CRITICAL: %d/%d (%.0f%%)", balance.used, balance.monthly_cap, usage_ratio * 100)

        elif usage_ratio >= DAEMON_BUDGET_ALERT_THRESHOLD and not _budget_alert_fired:
            _budget_alert_fired = True
            emit_event("daemon", "budget_warning", {
                "used": balance.used,
                "cap": balance.monthly_cap,
                "usage_percent": round(usage_ratio * 100),
                "message": f"Cloud budget at {usage_ratio:.0%} — {balance.remaining} credits remaining",
            })
            log.info("Budget WARNING: %d/%d (%.0f%%)", balance.used, balance.monthly_cap, usage_ratio * 100)

    except Exception as e:
        log.warning("Budget alert check failed: %s", e)


# ── Feature 4: Work Schedule Prewarming ──────────────────────────────
def _record_daily_activity() -> None:
    """Log today's first-activity timestamp for prewarming predictions."""
    try:
        data = {"samples": []}
        if DAEMON_PREWARM_DATA_FILE.exists():
            data = json.loads(DAEMON_PREWARM_DATA_FILE.read_text(encoding="utf-8"))

        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        # Don't duplicate today's entry
        if any(s["date"] == today for s in data["samples"]):
            return

        now = datetime.now(timezone.utc)
        data["samples"].append({
            "date": today,
            "first_active_utc": now.isoformat(),
            "hour": now.hour,
            "minute": now.minute,
        })

        # Keep last 30 days
        data["samples"] = data["samples"][-30:]

        DAEMON_PREWARM_DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
        DAEMON_PREWARM_DATA_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
        log.info("Recorded daily activity: %s %02d:%02d UTC", today, now.hour, now.minute)
    except Exception as e:
        log.warning("Failed to record daily activity: %s", e)


def _check_prewarm() -> None:
    """Pre-load model before predicted start time."""
    global _last_prewarm_check

    now_mono = time.monotonic()
    if now_mono - _last_prewarm_check < 60:  # Check every 60s
        return
    _last_prewarm_check = now_mono

    try:
        if not DAEMON_PREWARM_DATA_FILE.exists():
            return

        data = json.loads(DAEMON_PREWARM_DATA_FILE.read_text(encoding="utf-8"))
        samples = data.get("samples", [])

        if len(samples) < DAEMON_PREWARM_MIN_SAMPLES:
            return

        # Compute average start time from recent samples
        total_minutes = 0
        for s in samples[-DAEMON_PREWARM_MIN_SAMPLES:]:
            total_minutes += s["hour"] * 60 + s["minute"]
        avg_minutes = total_minutes / min(len(samples), DAEMON_PREWARM_MIN_SAMPLES)
        avg_hour = int(avg_minutes // 60)
        avg_minute = int(avg_minutes % 60)

        # Check if we're in the prewarm window
        now = datetime.now(timezone.utc)
        now_minutes = now.hour * 60 + now.minute
        target_minutes = avg_hour * 60 + avg_minute - DAEMON_PREWARM_LEAD_MINUTES

        # Handle midnight wraparound
        if target_minutes < 0:
            target_minutes += 1440

        diff = now_minutes - target_minutes
        if 0 <= diff <= DAEMON_PREWARM_LEAD_MINUTES:
            log.info("Prewarming model — predicted start ~%02d:%02d UTC", avg_hour, avg_minute)
            if _inference_manager is not None:
                import asyncio
                try:
                    asyncio.run(_inference_manager.health_check())
                except Exception:
                    pass

            from core.autonomic.events import emit_event
            emit_event("daemon", "prewarm", {
                "predicted_start_utc": f"{avg_hour:02d}:{avg_minute:02d}",
                "model": INFERENCE_MODEL,
            })
    except Exception as e:
        log.warning("Prewarm check failed: %s", e)


# ── Feature 5: Log Rotation ─────────────────────────────────────────
def _check_log_rotation() -> None:
    """Rotate oversized log files across the entire logs/ directory."""
    global _last_log_rotation

    now = time.monotonic()
    if now - _last_log_rotation < DAEMON_LOG_ROTATION_INTERVAL_SEC:
        return
    _last_log_rotation = now

    logs_dir = PROJECT_ROOT / "logs"
    if not logs_dir.exists():
        return

    rotated = 0
    for pattern in ("**/*.jsonl", "**/*.log"):
        for log_file in logs_dir.glob(pattern):
            try:
                size = log_file.stat().st_size
                if size <= DAEMON_LOG_ROTATION_MAX_BYTES:
                    continue

                lines = log_file.read_text(encoding="utf-8", errors="replace").strip().split("\n")
                if len(lines) <= DAEMON_LOG_ROTATION_KEEP_LINES:
                    continue

                # Keep last N lines
                trimmed = lines[-DAEMON_LOG_ROTATION_KEEP_LINES:]
                log_file.write_text("\n".join(trimmed) + "\n", encoding="utf-8")
                rotated += 1
                log.info("Rotated %s: %d -> %d lines", log_file.name, len(lines), len(trimmed))
            except OSError as e:
                log.warning("Failed to rotate %s: %s", log_file, e)

    if rotated:
        try:
            from core.autonomic.events import emit_event
            emit_event("daemon", "log_rotation", {"files_rotated": rotated})
        except Exception as e:
            log.debug("log_rotation emit_event suppressed: %s", e)


# ── Heartbeat ─────────────────────────────────────────────────────────
def heartbeat_tick() -> None:
    """Single heartbeat cycle — runs all checks. Never raises."""
    checks = [
        ("input_activity", _check_input_activity),
        ("local_inference", _check_local_inference),
        ("vault_watcher", _check_vault_changes),
        ("session_close", _check_stale_sessions),
        ("budget_alert", _check_budget_alerts),
        ("prewarm", _check_prewarm),
        ("log_rotation", _check_log_rotation),
    ]
    for name, fn in checks:
        try:
            fn()
        except Exception as e:
            log.error("Check '%s' crashed: %s: %s", name, type(e).__name__, e)


# ── Lifecycle ─────────────────────────────────────────────────────────
def _init_state() -> None:
    """Initialize daemon state variables. Called by both standalone and embedded modes."""
    global _running, _start_time
    global _budget_alert_fired, _budget_critical_fired, _today_activity_logged
    global _inference_manager, _restart_attempts, _restart_window_start
    global _session_warning_session_id
    _running = True
    _start_time = time.monotonic()
    _budget_alert_fired = False
    _budget_critical_fired = False
    _today_activity_logged = False
    _session_warning_session_id = None
    _restart_attempts = 0
    _restart_window_start = None
    _inference_manager = _init_inference_manager()


def start(foreground: bool = False) -> None:
    """Start the daemon heartbeat loop."""
    if not foreground:
        DAEMON_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        flags = 0
        if sys.platform == "win32":
            flags = subprocess.CREATE_NO_WINDOW
        # Use venv Python, not sys.executable — prevents wrong interpreter
        # when launched from a shell with miniconda/other Python on PATH.
        bin_dir = PROJECT_ROOT / ".venv" / ("Scripts" if sys.platform == "win32" else "bin")
        # Prefer pythonw (no console window) on Windows, fall back to python
        venv_python = bin_dir / "pythonw.exe" if sys.platform == "win32" else bin_dir / "python"
        if not venv_python.exists():
            venv_python = bin_dir / ("python.exe" if sys.platform == "win32" else "python")
        if not venv_python.exists():
            venv_python = Path(sys.executable)
        subprocess.Popen(
            [str(venv_python), "-m", "core.autonomic.daemon"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            cwd=str(PROJECT_ROOT),
            creationflags=flags,
        )
        return

    # Write PID file
    DAEMON_PID_FILE.parent.mkdir(parents=True, exist_ok=True)
    DAEMON_PID_FILE.write_text(str(os.getpid()), encoding="utf-8")

    # Configure logging
    logging.basicConfig(
        filename=str(DAEMON_LOG_FILE),
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    _init_state()

    log.info("Daemon started (PID %d)", os.getpid())

    def _signal_handler(signum, frame):
        log.info("Signal %s received — stopping", signum)
        stop()

    if sys.platform == "win32":
        signal.signal(signal.SIGBREAK, _signal_handler)
    else:
        signal.signal(signal.SIGTERM, _signal_handler)

    try:
        while _running:
            if DAEMON_STOP_FILE.exists():
                DAEMON_STOP_FILE.unlink(missing_ok=True)
                log.info("Stop file detected — shutting down")
                break
            try:
                heartbeat_tick()
            except Exception as e:
                log.error("Heartbeat: %s: %s", type(e).__name__, e, exc_info=True)
            time.sleep(DAEMON_HEARTBEAT_INTERVAL_SEC)
    except KeyboardInterrupt:
        pass
    except Exception as e:
        log.error("Daemon crashed: %s: %s", type(e).__name__, e, exc_info=True)
    finally:
        stop()


def stop() -> None:
    """Stop the daemon and clean up PID file."""
    global _running
    _running = False
    log.info("Daemon stopped")
    try:
        if DAEMON_PID_FILE.exists():
            DAEMON_PID_FILE.unlink()
    except OSError:
        pass


def is_running() -> bool:
    """Check if daemon is running via PID file."""
    if not DAEMON_PID_FILE.exists():
        return False
    try:
        pid = int(DAEMON_PID_FILE.read_text(encoding="utf-8").strip())
        # os.kill(pid, 0) is unreliable on Windows — use ctypes
        if sys.platform == "win32":
            kernel32 = ctypes.windll.kernel32
            handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
            if handle:
                kernel32.CloseHandle(handle)
                return True
            # Process gone — clean up stale PID file
            DAEMON_PID_FILE.unlink(missing_ok=True)
            return False
        else:
            os.kill(pid, 0)
            return True
    except (ValueError, OSError, SystemError):
        DAEMON_PID_FILE.unlink(missing_ok=True)
        return False


def install_service() -> None:
    """Register Windows Task Scheduler entry for logon auto-start."""
    exe = sys.executable.replace("python.exe", "pythonw.exe")
    subprocess.run(
        [
            "schtasks", "/create",
            "/tn", "OIKOS_DAEMON",
            "/tr", f'cmd /c "cd /d {PROJECT_ROOT} && \"{exe}\" -m core.autonomic.daemon"',
            "/sc", "onlogon",
            "/f",
        ],
        check=True,
    )


def uninstall_service() -> None:
    """Remove Windows Task Scheduler entry."""
    subprocess.run(
        ["schtasks", "/delete", "/tn", "OIKOS_DAEMON", "/f"],
        check=True,
    )


def get_status() -> dict:
    """Return daemon status dict."""
    from core.autonomic.fsm import get_current_state

    running = _running or is_running()
    uptime = None
    if running and _start_time > 0:
        uptime = time.monotonic() - _start_time

    return {
        "running": running,
        "pid": int(DAEMON_PID_FILE.read_text(encoding="utf-8").strip()) if DAEMON_PID_FILE.exists() else None,
        "fsm_state": get_current_state().value,
        "inference_manager": _inference_manager.backend_name() if _inference_manager else None,
        "restart_attempts": _restart_attempts,
        "uptime_seconds": uptime,
    }


# ── Entry point for foreground mode (python -m core.autonomic.daemon) ─
if __name__ == "__main__":
    start(foreground=True)
