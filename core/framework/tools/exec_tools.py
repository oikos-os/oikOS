"""Exec tools — scoped shell execution via subprocess."""

import re
import subprocess
import sys
from pathlib import Path

from core.framework import oikos_tool, PrivacyTier, AutonomyLevel

_MAX_OUTPUT = 10_000
_TIMEOUT_SECONDS = 30

# Destructive commands blocked by regex patterns (case-insensitive)
_DESTRUCTIVE_PATTERNS: list[re.Pattern[str]] = [
    # rm with recursive+force flags in any order, targeting root or common roots
    re.compile(r"rm\s+.*-\w*r\w*f\w*.*\s+/(?:\s|$)", re.IGNORECASE),
    re.compile(r"rm\s+.*-\w*f\w*r\w*.*\s+/(?:\s|$)", re.IGNORECASE),
    # format any drive
    re.compile(r"\bformat\s+[a-zA-Z]:", re.IGNORECASE),
    # del with recursive/quiet flags targeting drive roots
    re.compile(r"\bdel\s+.*/s.*[a-zA-Z]:\\", re.IGNORECASE),
    re.compile(r"\bdel\s+.*/q.*[a-zA-Z]:\\", re.IGNORECASE),
    # PowerShell destructive cmdlets
    re.compile(r"\bRemove-Item\s+.*-Recurse", re.IGNORECASE),
    re.compile(r"\bClear-Disk\b", re.IGNORECASE),
    re.compile(r"\bFormat-Volume\b", re.IGNORECASE),
    # Unix disk-level destructive
    re.compile(r"\bmkfs\b", re.IGNORECASE),
    re.compile(r"\bdd\s+.*\bof=/dev/", re.IGNORECASE),
]

# Sacred boundary — resolved once at import time
_SACRED_BOUNDARY = Path("D:/Development/OIKOS_OMEGA").resolve()


def _check_prohibited_command(command: str) -> None:
    for pattern in _DESTRUCTIVE_PATTERNS:
        if pattern.search(command):
            raise PermissionError("PROHIBITED: destructive command")
    # Resolve path-like tokens and check against sacred boundary
    for token in command.split():
        if "/" not in token and "\\" not in token:
            continue  # skip non-path tokens (commands, flags, etc.)
        try:
            resolved = Path(token).resolve()
        except (ValueError, OSError):
            continue
        if resolved.is_relative_to(_SACRED_BOUNDARY):
            raise PermissionError("PROHIBITED: targets sacred boundary")


def _validate_cwd(cwd: str) -> str | None:
    if not cwd:
        return None
    from core.interface.config import FILE_AGENT_ALLOWED_PATHS
    resolved = Path(cwd).resolve()
    # Check prohibited
    prohibited = Path("D:/Development/OIKOS_OMEGA").resolve()
    if resolved.is_relative_to(prohibited):
        raise PermissionError("PROHIBITED: requested working directory is outside allowed scope")
    # Must be within an allowed path
    for allowed_path in FILE_AGENT_ALLOWED_PATHS:
        try:
            allowed_resolved = Path(allowed_path).resolve()
        except (ValueError, OSError):
            continue
        if resolved.is_relative_to(allowed_resolved):
            return str(resolved)
    raise PermissionError("PROHIBITED: requested working directory is outside allowed scope")


@oikos_tool(
    name="oikos_system_exec",
    description="Execute a shell command within allowed scope",
    privacy=PrivacyTier.SENSITIVE,
    autonomy=AutonomyLevel.ASK_FIRST,
    toolset="system",
    destructive=True,
    search_hint="execute shell command run subprocess terminal",
    group="system",
)
def system_exec(command: str, cwd: str = "") -> dict:
    _check_prohibited_command(command)
    validated_cwd = _validate_cwd(cwd)

    if sys.platform == "win32":
        cmd = ["powershell", "-Command", command]
    else:
        cmd = ["/bin/sh", "-c", command]

    try:
        kwargs = {}
        if sys.platform == "win32":
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        proc = subprocess.run(
            cmd,
            cwd=validated_cwd,
            capture_output=True,
            text=True,
            timeout=_TIMEOUT_SECONDS,
            **kwargs,
        )
        stdout = proc.stdout
        stderr = proc.stderr
        truncated = False
        combined_len = len(stdout) + len(stderr)
        if combined_len > _MAX_OUTPUT:
            # Truncate stdout first, then stderr
            if len(stdout) > _MAX_OUTPUT:
                stdout = stdout[:_MAX_OUTPUT]
                stderr = ""
            else:
                stderr = stderr[:_MAX_OUTPUT - len(stdout)]
            truncated = True
        return {
            "stdout": stdout,
            "stderr": stderr,
            "exit_code": proc.returncode,
            "truncated": truncated,
        }
    except subprocess.TimeoutExpired:
        return {
            "stdout": "",
            "stderr": f"Command timed out after {_TIMEOUT_SECONDS}s",
            "exit_code": -1,
            "truncated": False,
        }
