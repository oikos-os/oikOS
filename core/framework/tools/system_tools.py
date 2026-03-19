"""System tools — status, state, gauntlet, session management, daemon, config, notify."""

import json
from pathlib import Path

from core.framework import oikos_tool, PrivacyTier, AutonomyLevel


@oikos_tool(
    name="oikos_system_status",
    description="Get system status: Ollama health, provider registry, daemon state",
    privacy=PrivacyTier.SAFE,
    autonomy=AutonomyLevel.SAFE,
    toolset="system",
)
def system_status() -> dict:
    from core.autonomic.daemon import get_status
    return get_status()


@oikos_tool(
    name="oikos_state_get",
    description="Get the current FSM state (IDLE, ACTIVE, ASLEEP)",
    privacy=PrivacyTier.SAFE,
    autonomy=AutonomyLevel.SAFE,
    toolset="system",
)
def state_get() -> dict:
    from core.autonomic.fsm import get_current_state, get_last_transition_time
    state = get_current_state()
    return {"state": state.value, "last_transition": get_last_transition_time()}


@oikos_tool(
    name="oikos_state_transition",
    description="Transition FSM to a new state (idle, active, asleep)",
    privacy=PrivacyTier.SAFE,
    autonomy=AutonomyLevel.ASK_FIRST,
    toolset="system",
)
def state_transition(target: str, trigger: str = "mcp_tool") -> dict:
    from core.autonomic.fsm import transition_to, SystemState
    target_state = SystemState(target.lower())
    return transition_to(target_state, trigger=trigger)


@oikos_tool(
    name="oikos_gauntlet_run",
    description="Run the adversarial security gauntlet (10 probes, consensus N=3)",
    privacy=PrivacyTier.SENSITIVE,
    autonomy=AutonomyLevel.ASK_FIRST,
    toolset="system",
)
def gauntlet_run(consensus_runs: int = 3) -> dict:
    from core.agency.adversarial import run_gauntlet
    summary = run_gauntlet(consensus_runs=consensus_runs)
    return {
        "passed": summary.passed,
        "failed": summary.failed,
        "soft_fails": summary.soft_fails,
        "total": summary.total,
        "score": f"{summary.passed}/{summary.total}",
        "regressions": summary.regressions,
    }


@oikos_tool(
    name="oikos_gauntlet_generate",
    description="Generate novel adversarial probes targeting uncovered attack categories",
    privacy=PrivacyTier.SENSITIVE,
    autonomy=AutonomyLevel.ASK_FIRST,
    toolset="system",
)
def gauntlet_generate(count: int = 5, stage: bool = False) -> dict:
    from core.agency.adversarial import generate_novel_probes, stage_novel_probes
    probes = generate_novel_probes(count=count)
    result = {
        "generated": len(probes),
        "probes": [{"probe_id": p.probe_id, "query": p.query[:100], "description": p.description} for p in probes],
    }
    if stage and probes:
        staged = stage_novel_probes(probes)
        result["staged"] = staged
    return result


@oikos_tool(
    name="oikos_session_start",
    description="Start or resume an oikOS session",
    privacy=PrivacyTier.SAFE,
    autonomy=AutonomyLevel.SAFE,
    toolset="system",
)
def session_start() -> dict:
    from core.memory.session import get_or_create_session
    return get_or_create_session()


@oikos_tool(
    name="oikos_session_close",
    description="Close the current session with a reason",
    privacy=PrivacyTier.SAFE,
    autonomy=AutonomyLevel.ASK_FIRST,
    toolset="system",
)
def session_close(reason: str = "explicit") -> dict:
    from core.memory.session import close_session
    result = close_session(reason=reason)
    return result or {"status": "no active session"}


@oikos_tool(
    name="oikos_daemon_start",
    description="Start the oikOS daemon (heartbeat, VRAM monitoring, memory consolidation)",
    privacy=PrivacyTier.SAFE,
    autonomy=AutonomyLevel.ASK_FIRST,
    toolset="system",
)
def daemon_start() -> dict:
    try:
        from core.autonomic.daemon import start
        start()
        return {"status": "started"}
    except Exception as exc:
        return {"status": "error", "message": str(exc)}


@oikos_tool(
    name="oikos_daemon_stop",
    description="Stop the oikOS daemon cleanly",
    privacy=PrivacyTier.SAFE,
    autonomy=AutonomyLevel.ASK_FIRST,
    toolset="system",
)
def daemon_stop() -> dict:
    try:
        from core.autonomic.daemon import stop
        stop()
        return {"status": "stopped"}
    except Exception as exc:
        return {"status": "error", "message": str(exc)}


_SECRET_KEYS = {"key", "secret", "token", "password"}


def _is_secret_key(key: str) -> bool:
    key_lower = key.lower()
    return any(s in key_lower for s in _SECRET_KEYS)


@oikos_tool(
    name="oikos_config_get",
    description="Read an oikOS configuration value (redacts secrets)",
    privacy=PrivacyTier.SENSITIVE,
    autonomy=AutonomyLevel.SAFE,
    toolset="system",
)
def config_get(key: str, source: str = "settings") -> dict:
    from core.interface.config import PROJECT_ROOT

    if source == "settings":
        config_file = PROJECT_ROOT / "settings.json"
        try:
            data = json.loads(config_file.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {"status": "error", "message": "settings.json not found"}
        except json.JSONDecodeError as exc:
            return {"status": "error", "message": f"Invalid JSON: {exc}"}
        value = data.get(key)
        if value is None:
            return {"status": "not_found", "key": key, "source": "settings.json"}
    elif source == "providers":
        config_file = PROJECT_ROOT / "providers.toml"
        if not config_file.exists():
            return {"status": "error", "message": "providers.toml not found"}
        try:
            import tomllib
            data = tomllib.loads(config_file.read_text(encoding="utf-8"))
        except Exception as exc:
            return {"status": "error", "message": f"TOML parse error: {exc}"}
        value = data.get(key)
        if value is None:
            return {"status": "not_found", "key": key, "source": "providers.toml"}
    else:
        return {"status": "error", "message": f"Unknown source '{source}'. Use 'settings' or 'providers'."}

    if _is_secret_key(key):
        value = "[REDACTED]"

    return {"key": key, "value": value, "source": str(config_file.name)}


@oikos_tool(
    name="oikos_config_set",
    description="Set a runtime configuration value in settings.json",
    privacy=PrivacyTier.SENSITIVE,
    autonomy=AutonomyLevel.ASK_FIRST,
    toolset="system",
)
def config_set(key: str, value: str, reason: str = "") -> dict:
    from core.interface.config import PROJECT_ROOT

    if _is_secret_key(key):
        return {
            "status": "refused",
            "message": f"Cannot set secret key '{key}' via config_set. Manage secrets via environment variables.",
        }

    config_file = PROJECT_ROOT / "settings.json"
    try:
        data = json.loads(config_file.read_text(encoding="utf-8")) if config_file.exists() else {}
    except json.JSONDecodeError:
        data = {}

    data[key] = value
    config_file.write_text(json.dumps(data, indent=2), encoding="utf-8")

    return {"status": "updated", "key": key, "source": "settings.json"}


@oikos_tool(
    name="oikos_notify",
    description="Send a toast notification to the Architect's desktop",
    privacy=PrivacyTier.SAFE,
    autonomy=AutonomyLevel.SAFE,
    toolset="system",
)
def notify(title: str, message: str, severity: str = "info") -> dict:
    import datetime as _dt
    from core.interface.config import PROJECT_ROOT

    log_file = PROJECT_ROOT / "logs" / "notifications.jsonl"
    log_file.parent.mkdir(parents=True, exist_ok=True)

    entry = {
        "timestamp": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "title": title,
        "message": message,
        "severity": severity,
    }
    with log_file.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry) + "\n")

    return {"status": "sent", "title": title}
