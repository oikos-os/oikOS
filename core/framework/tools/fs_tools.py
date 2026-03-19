"""Filesystem tools — scoped file operations via FileAgent."""

from core.framework import oikos_tool, PrivacyTier, AutonomyLevel

_file_agent = None


def _get_agent():
    """Lazy-init shared FileAgent instance."""
    global _file_agent
    if _file_agent is None:
        from core.agency.file_agent import FileAgent
        from core.agency.autonomy import AutonomyMatrix
        from core.agency.approval import ApprovalQueue
        from core.interface.config import AUTONOMY_MATRIX_PATH
        _file_agent = FileAgent(AutonomyMatrix(AUTONOMY_MATRIX_PATH), ApprovalQueue())
    return _file_agent


@oikos_tool(
    name="oikos_fs_read",
    description="Read a file's contents (scope-validated, respects sacred boundary)",
    privacy=PrivacyTier.SENSITIVE,
    autonomy=AutonomyLevel.SAFE,
    toolset="file",
)
def fs_read(path: str) -> dict:
    agent = _get_agent()
    content = agent.read_file(path)
    return {"path": path, "content": content, "length": len(content)}


@oikos_tool(
    name="oikos_fs_list",
    description="List directory contents (scope-validated)",
    privacy=PrivacyTier.SENSITIVE,
    autonomy=AutonomyLevel.SAFE,
    toolset="file",
)
def fs_list(path: str) -> dict:
    agent = _get_agent()
    entries = agent.list_directory(path)
    return {"path": path, "entries": entries, "count": len(entries)}


@oikos_tool(
    name="oikos_fs_search",
    description="Search for files by name pattern in a directory",
    privacy=PrivacyTier.SENSITIVE,
    autonomy=AutonomyLevel.SAFE,
    toolset="file",
)
def fs_search(directory: str, pattern: str) -> dict:
    agent = _get_agent()
    matches = agent.search_files(directory, pattern)
    return {"directory": directory, "pattern": pattern, "matches": matches, "count": len(matches)}


@oikos_tool(
    name="oikos_fs_write",
    description="Write content to a file (requires approval, scope-validated)",
    privacy=PrivacyTier.SENSITIVE,
    autonomy=AutonomyLevel.ASK_FIRST,
    toolset="file",
)
def fs_write(path: str, content: str, reason: str = "MCP tool write") -> dict:
    agent = _get_agent()
    proposal = agent.write_file(path, content, reason=reason)
    return {
        "status": "proposal_created",
        "proposal_id": proposal.proposal_id,
        "path": path,
        "reason": reason,
    }


@oikos_tool(
    name="oikos_fs_edit",
    description="Surgical edit: replace old_string with new_string in a file (requires approval)",
    privacy=PrivacyTier.SENSITIVE,
    autonomy=AutonomyLevel.ASK_FIRST,
    toolset="file",
)
def fs_edit(path: str, old_string: str, new_string: str, reason: str = "MCP tool edit") -> dict:
    agent = _get_agent()
    content = agent.read_file(path)
    if old_string not in content:
        return {"status": "error", "message": f"old_string not found in {path}"}
    new_content = content.replace(old_string, new_string, 1)
    proposal = agent.write_file(path, new_content, reason=reason)
    return {
        "status": "proposal_created",
        "proposal_id": proposal.proposal_id,
        "path": path,
        "reason": reason,
    }


@oikos_tool(
    name="oikos_fs_move",
    description="Move a file between allowed paths (requires approval)",
    privacy=PrivacyTier.SENSITIVE,
    autonomy=AutonomyLevel.ASK_FIRST,
    toolset="file",
)
def fs_move(source: str, destination: str, reason: str = "MCP tool move") -> dict:
    agent = _get_agent()
    proposal = agent.move_file(source, destination, reason=reason)
    return {
        "status": "proposal_created",
        "proposal_id": proposal.proposal_id,
        "source": source,
        "destination": destination,
        "reason": reason,
    }


@oikos_tool(
    name="oikos_fs_copy",
    description="Copy a file between allowed paths (requires approval)",
    privacy=PrivacyTier.SENSITIVE,
    autonomy=AutonomyLevel.ASK_FIRST,
    toolset="file",
)
def fs_copy(source: str, destination: str, reason: str = "MCP tool copy") -> dict:
    agent = _get_agent()
    proposal = agent.copy_file(source, destination, reason=reason)
    return {
        "status": "proposal_created",
        "proposal_id": proposal.proposal_id,
        "source": source,
        "destination": destination,
        "reason": reason,
    }


@oikos_tool(
    name="oikos_fs_delete",
    description="Delete a file (never vault, never OIKOS_OMEGA, requires approval)",
    privacy=PrivacyTier.SENSITIVE,
    autonomy=AutonomyLevel.ASK_FIRST,
    toolset="file",
)
def fs_delete(path: str, reason: str = "MCP tool delete") -> dict:
    agent = _get_agent()
    proposal = agent.delete_file(path, reason=reason)
    return {
        "status": "proposal_created",
        "proposal_id": proposal.proposal_id,
        "path": path,
        "reason": reason,
    }
