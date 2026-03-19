"""Git tools — scoped git status and log for allowed repositories."""

import subprocess
from pathlib import Path

from core.framework import oikos_tool, PrivacyTier, AutonomyLevel


_PROHIBITED_REPO_PATHS = [
    "D:/Development/OIKOS_OMEGA",
]


def _validate_repo_scope(repo_path: str) -> Path:
    """Resolve and validate repo_path is in FILE_AGENT_ALLOWED_PATHS.

    Returns resolved Path on success, raises ValueError on scope violation.
    """
    from core.interface.config import FILE_AGENT_ALLOWED_PATHS

    resolved = Path(repo_path).resolve()

    for prohibited in _PROHIBITED_REPO_PATHS:
        if resolved.is_relative_to(Path(prohibited).resolve()):
            raise ValueError(f"PROHIBITED repo path: {repo_path}")

    resolved_str = resolved.as_posix()
    for allowed_raw in FILE_AGENT_ALLOWED_PATHS:
        allowed = Path(allowed_raw).resolve().as_posix()
        if resolved_str == allowed or resolved_str.startswith(allowed + "/"):
            return resolved

    raise ValueError(
        f"Path outside allowed scope: {repo_path}. "
        f"Allowed roots: {list(FILE_AGENT_ALLOWED_PATHS.keys())}"
    )


def _run_git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo)] + list(args),
        capture_output=True,
        text=True,
        timeout=15,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"git exited {result.returncode}")
    return result.stdout


@oikos_tool(
    name="oikos_git_status",
    description="Get git status for a repository in allowed scope",
    privacy=PrivacyTier.SENSITIVE,
    autonomy=AutonomyLevel.SAFE,
    toolset="git",
)
def git_status(repo_path: str) -> dict:
    try:
        repo = _validate_repo_scope(repo_path)
    except ValueError as exc:
        return {"status": "error", "message": str(exc)}

    try:
        porcelain = _run_git(repo, "status", "--porcelain")
        branch = _run_git(repo, "branch", "--show-current").strip()
    except RuntimeError:
        return {"status": "error", "message": "git command failed"}

    staged, modified, untracked = [], [], []
    for line in porcelain.splitlines():
        if len(line) < 3:
            continue
        index_status = line[0]
        worktree_status = line[1]
        filepath = line[3:]
        if index_status != " " and index_status != "?":
            staged.append(filepath)
        if worktree_status == "M":
            modified.append(filepath)
        if index_status == "?" and worktree_status == "?":
            untracked.append(filepath)

    return {
        "repo": repo_path,
        "branch": branch,
        "clean": not bool(staged or modified or untracked),
        "staged": staged,
        "modified": modified,
        "untracked": untracked,
    }


@oikos_tool(
    name="oikos_git_log",
    description="Get recent git commits for a repository in allowed scope",
    privacy=PrivacyTier.SENSITIVE,
    autonomy=AutonomyLevel.SAFE,
    toolset="git",
)
def git_log(repo_path: str, count: int = 10) -> list[dict]:
    try:
        repo = _validate_repo_scope(repo_path)
    except ValueError as exc:
        return [{"status": "error", "message": str(exc)}]

    count = min(count, 50)

    try:
        raw = _run_git(repo, "log", f"--max-count={count}", "--format=%H|%an|%aI|%s")
    except RuntimeError:
        return [{"status": "error", "message": "git command failed"}]

    commits = []
    for line in raw.splitlines():
        if not line.strip():
            continue
        parts = line.split("|", 3)
        if len(parts) == 4:
            commits.append({
                "hash": parts[0],
                "author": parts[1],
                "date": parts[2],
                "message": parts[3],
            })
    return commits
