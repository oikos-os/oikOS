from __future__ import annotations

import json
import logging
from pathlib import Path

from core.interface.models import ActionClass

log = logging.getLogger(__name__)

# ── Tool Registry ────────────────────────────────────────────────────
# Maps concrete tool names to abstract action types in the matrix.
# Module 2 ships the base mapping; Module 3+ extends it.
_DEFAULT_TOOL_REGISTRY: dict[str, str] = {
    "file_read": "read_file",
    "file_search": "search_files",
    "system_status": "check_status",
    "web_navigate": "read_web",
    "vault_search": "vault_search",
    "file_write": "write_file",
    "browser_submit": "browser_form",
    "message_send": "send_message",
    "api_write": "external_api_write",
    "api_call": "external_api_call",
    "vault_delete": "delete_vault",
    "identity_modify": "modify_identity",
    "source_modify": "modify_source",
}


class AutonomyMatrix:
    def __init__(self, config_path: Path):
        if not config_path.exists():
            raise FileNotFoundError(f"Autonomy matrix config not found: {config_path}")
        raw = json.loads(config_path.read_text(encoding="utf-8"))
        actions = raw["actions"]
        self._rules: dict[str, ActionClass] = {}
        valid = {e.value for e in ActionClass}
        for action_type, entry in actions.items():
            cat = entry["category"]
            if cat not in valid:
                raise ValueError(f"Invalid category {cat!r} for action {action_type!r}")
            self._rules[action_type] = ActionClass(cat)
        self._tool_registry: dict[str, str] = dict(_DEFAULT_TOOL_REGISTRY)

    def classify(self, action_type: str) -> ActionClass:
        return self._rules.get(action_type, ActionClass.PROHIBITED)

    def classify_tool(self, tool_name: str) -> ActionClass:
        action_type = self._tool_registry.get(tool_name)
        if action_type is None:
            return ActionClass.PROHIBITED
        return self.classify(action_type)

    def register_tool(self, tool_name: str, action_type: str) -> None:
        self._tool_registry[tool_name] = action_type
