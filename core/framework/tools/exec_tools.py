"""Exec tools — scoped shell execution via subprocess."""

import subprocess
import sys
from pathlib import Path

from core.framework import oikos_tool, PrivacyTier, AutonomyLevel

_MAX_OUTPUT = 10_000
_TIMEOUT_SECONDS = 30

# Commands that target system destruction or the sacred boundary
_PROHIBITED_PATTERNS = [
    "rm -rf /",
    "format C:",
    "del /s /q C:",
    "D:/Development/OIKOS_OMEGA",
    "D:\\Development\\OIKOS_OMEGA",
]


def _check_prohibited_command(command: str) -> None:
    lower = command.lower()
    for pattern in _PROHIBITED_PATTERNS:
        if pattern.lower() in lower:
            raise PermissionError(f"PROHIBITED command pattern: {pattern!r}")


def _validate_cwd(cwd: str) -> str | None:
    if not cwd:
        return None
    from core.interface.config import FILE_AGENT_ALLOWED_PATHS
    resolved = Path(cwd).resolve()
    # Check prohibited
    prohibited = Path("D:/Development/OIKOS_OMEGA").resolve()
    if resolved.is_relative_to(prohibited):
        raise PermissionError(f"PROHIBITED cwd: {resolved}")
    # Must be within an allowed path
    for allowed_path in FILE_AGENT_ALLOWED_PATHS:
        try:
            allowed_resolved = Path(allowed_path).resolve()
        except (ValueError, OSError):
            continue
        if resolved.is_relative_to(allowed_resolved):
            return str(resolved)
    raise PermissionError(f"cwd outside allowed scope: {resolved}")


@oikos_tool(
    name="oikos_system_exec",
    description="Execute a shell command within allowed scope",
    privacy=PrivacyTier.SENSITIVE,
    autonomy=AutonomyLevel.ASK_FIRST,
    toolset="system",
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
