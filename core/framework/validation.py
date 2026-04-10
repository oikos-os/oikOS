"""Framework-level input validators for MCP tools.

Any tool that accepts a filename or path from an MCP client MUST call
validate_filename() before constructing filesystem paths. This prevents
path traversal attacks (../../sensitive/file).
"""

from pathlib import Path


def validate_filename(filename: str) -> str:
    """Validate that a filename has no path components or traversal.

    Returns the cleaned filename on success.
    Raises ValueError on invalid input.
    """
    if not filename or not filename.strip():
        raise ValueError("Filename cannot be empty")
    if Path(filename).name != filename:
        raise ValueError(f"Invalid filename: path components not allowed")
    if ".." in filename:
        raise ValueError(f"Invalid filename: path traversal not allowed")
    return filename
