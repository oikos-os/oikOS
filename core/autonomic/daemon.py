"""OS Daemon — heartbeat loop, VRAM yield, Ollama health, service install,
vault file watcher, session auto-close, budget alerts, prewarming, log rotation."""

from __future__ import annotations

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
from pathlib import Path

from core.interface.config import (
    DAEMON_BUDGET_ALERT_THRESHOLD,
    DAEMON_BUDGET_CHECK_INTERVAL_SEC,
    DAEMON_BUDGET_CRITICAL_THRESHOLD,
    DAEMON_HEALTH_CHECK_INTERVAL_SEC,
    DAEMON_HEALTH_FAILURES_RESTART,
    DAEMON_HEARTBEAT_INTERVAL_SEC,
    DAEMON_IDLE_TIMEOUT_MINUTES,
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
    DAEMON_VRAM_YIELD_THRESHOLD_MB,
    INFERENCE_MODEL,
    PROJECT_ROOT,
)

log = logging.getLogger(__name__)

# ── Module State ──────────────────────────────────────────────────────
_running: bool = False
_vram_yielded: bool = False
_health_failures: int = 0
_last_health_check: float = 0.0
_inference_active: bool = False
_start_time: float = 0.0

# Interval trackers for new features
_last_vault_mtime: float = 0.0
_last_session_check: float = 0.0
_last_budget_check: float = 0.0
_budget_alert_fired: bool = False
_budget_critical_fired: bool = False
_last_log_rotation: float = 0.0
_last_prewarm_check: float = 0.0
_today_activity_logged: bool = False


# ── Inference Guard ──────────────────────────────────────────────────
@contextmanager
def inference_active():
    """Context manager that prevents VRAM yield during inference."""
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
    threshold = DAEMON_IDLE_TIMEOUT_MINUTES * 60
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


def _check_vram_pressure() -> None:
    """Monitor VRAM usage. Yield model when pressure is high."""
    global _vram_yielded

    if _inference_active:
        return

    try:
        import pynvml

        pynvml.nvmlInit()
        handle = pynvml.nvmlDeviceGetHandleByIndex(0)
        info = pynvml.nvmlDeviceGetMemoryInfo(handle)
        used_mb = info.used // (1024 * 1024)
        pynvml.nvmlShutdown()
    except Exception:
        return

    threshold = DAEMON_VRAM_YIELD_THRESHOLD_MB

    if used_mb > threshold and not _vram_yielded:
        stop_kwargs = {"capture_output": True, "timeout": 30}
        if sys.platform == "win32":
            stop_kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        subprocess.run(["ollama", "stop", INFERENCE_MODEL], **stop_kwargs)
        _vram_yielded = True
        log.info("VRAM yield: unloaded %s (used=%dMB)", INFERENCE_MODEL, used_mb)
    elif used_mb < threshold * 0.8 and _vram_yielded:
        _warmup_model()
        _vram_yielded = False
        log.info("VRAM reload: loaded %s (used=%dMB)", INFERENCE_MODEL, used_mb)


def _check_ollama_health() -> None:
    """Periodic Ollama health ping. Restart after consecutive failures."""
    global _health_failures, _last_health_check

    now = time.monotonic()
    if now - _last_health_check < DAEMON_HEALTH_CHECK_INTERVAL_SEC:
        return
    _last_health_check = now

    try:
        import ollama

        ollama.Client().list()
        _health_failures = 0
    except Exception:
        _health_failures += 1
        log.warning("Ollama health check failed (%d/%d)", _health_failures, DAEMON_HEALTH_FAILURES_RESTART)
        if _health_failures >= DAEMON_HEALTH_FAILURES_RESTART:
            log.info("Restarting Ollama after %d failures", _health_failures)
            subprocess.Popen(
                ["ollama", "serve"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            _health_failures = 0


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
    """Close web UI sessions that have been inactive too long."""
    global _last_session_check

    now = time.monotonic()
    if now - _last_session_check < DAEMON_SESSION_CHECK_INTERVAL_SEC:
        return
    _last_session_check = now

    try:
        from core.memory.session import SESSION_STATE_FILE, _load_state, close_session

        state = _load_state()
        if state is None:
            return

        last_active = datetime.fromisoformat(state["last_active_at"])
        elapsed_min = (datetime.now(timezone.utc) - last_active).total_seconds() / 60

        if elapsed_min > DAEMON_SESSION_STALE_MINUTES:
            result = close_session()
            if result:
                log.info(
                    "Auto-closed stale session %s (inactive %.0f min, %d interactions)",
                    result["session_id"], elapsed_min, result.get("interaction_count", 0),
                )
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

    if _vram_yielded or _inference_active:
        return

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
            _warmup_model()

            from core.autonomic.events import emit_event
            emit_event("daemon", "prewarm", {
                "predicted_start_utc": f"{avg_hour:02d}:{avg_minute:02d}",
                "model": INFERENCE_MODEL,
            })
    except Exception as e:
        log.warning("Prewarm check failed: %s", e)


def _warmup_model() -> None:
    """Send a minimal inference request to load model into VRAM."""
    try:
        import ollama

        ollama.Client().generate(
            model=INFERENCE_MODEL,
            prompt="warmup",
            options={"num_predict": 1},
        )
    except Exception as e:
        log.warning("Model warmup failed: %s", e)


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
        except Exception:
            pass


# ── Heartbeat ─────────────────────────────────────────────────────────
def heartbeat_tick() -> None:
    """Single heartbeat cycle — runs all checks. Never raises."""
    checks = [
        ("input_activity", _check_input_activity),
        ("vram_pressure", _check_vram_pressure),
        ("ollama_health", _check_ollama_health),
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
    global _running, _start_time, _health_failures, _vram_yielded, _last_health_check
    global _budget_alert_fired, _budget_critical_fired, _today_activity_logged
    _running = True
    _start_time = time.monotonic()
    _health_failures = 0
    _vram_yielded = False
    _last_health_check = 0.0
    _budget_alert_fired = False
    _budget_critical_fired = False
    _today_activity_logged = False


def start(foreground: bool = False) -> None:
    """Start the daemon heartbeat loop."""
    if not foreground:
        DAEMON_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        flags = 0
        if sys.platform == "win32":
            flags = subprocess.CREATE_NO_WINDOW
        subprocess.Popen(
            [sys.executable, "-m", "core.autonomic.daemon"],
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
        "vram_yielded": _vram_yielded,
        "health_failures": _health_failures,
        "uptime_seconds": uptime,
    }


# ── Entry point for foreground mode (python -m core.autonomic.daemon) ─
if __name__ == "__main__":
    start(foreground=True)
