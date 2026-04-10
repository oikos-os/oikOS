"""Oracle tools — ORACLE division agent state (read-only)."""

import json
from pathlib import Path

from core.framework import oikos_tool, PrivacyTier, AutonomyLevel

_ORACLE_BASE = Path("D:/Development/ORACLE/agents")
_AGENT_STATE_PATHS = {
    "tempest": _ORACLE_BASE / "tempest" / "data" / "state.json",
    "sentinel": _ORACLE_BASE / "sentinel" / "data" / "state.json",
    "colossus": _ORACLE_BASE / "colossus" / "data" / "state.json",
    "forge": _ORACLE_BASE / "forge" / "data" / "state.json",
}


def _read_agent_state(state_path: Path) -> dict | None:
    """Return parsed state dict or None if file missing/invalid."""
    if not state_path.exists():
        return None
    try:
        return json.loads(state_path.read_text(encoding="utf-8"))
    except Exception:
        return None


@oikos_tool(
    name="oikos_oracle_status",
    description="Get ORACLE division agent status — TEMPEST, SENTINEL, COLOSSUS, FORGE state",
    privacy=PrivacyTier.SENSITIVE,
    autonomy=AutonomyLevel.SAFE,
    toolset="oracle",
    concurrent_safe=True,
    read_only=True,
    search_hint="oracle agents status tempest sentinel prediction",
    group="prediction",
)
def oracle_status() -> dict:
    agents: dict[str, dict] = {}

    for agent_name, state_path in _AGENT_STATE_PATHS.items():
        state = _read_agent_state(state_path)
        if state is None:
            agents[agent_name] = {"status": "not_found", "state_file": str(state_path)}
        else:
            agents[agent_name] = {
                "status": "active",
                "state_file": str(state_path),
                "last_run": state.get("last_run"),
                "positions": state.get("positions"),
                "daily_pnl": state.get("daily_pnl"),
                "errors": state.get("errors", []),
            }

    if all(v["status"] == "not_found" for v in agents.values()):
        return {"status": "no agents found"}

    return {"status": "ok", "agents": agents}
