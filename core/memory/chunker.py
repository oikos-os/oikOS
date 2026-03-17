"""Markdown parser — header-based splitting, tier classification, vault discovery."""

from __future__ import annotations

import hashlib
import logging
import re
from datetime import datetime, timezone
from pathlib import Path

from core.interface.config import PROJECT_ROOT, TIER_PATHS, VAULT_DIR
from core.interface.models import MemoryTier, VaultChunk

log = logging.getLogger(__name__)

_HEADING_RE = re.compile(r"^(#{1,3})\s+(.+)$", re.MULTILINE)
_SKIP_FILENAMES = {".gitkeep"}
_MIN_CHUNK_CHARS = 10
_WARN_CHUNK_TOKENS = 8000  # log warning if chunk likely exceeds this


def _normalize_path(path: Path) -> str:
    """Return forward-slash relative path from PROJECT_ROOT."""
    try:
        rel = path.resolve().relative_to(PROJECT_ROOT.resolve())
    except ValueError:
        rel = path
    return str(rel).replace("\\", "/")


def classify_tier(path: Path) -> MemoryTier:
    """Classify a file into a memory tier based on its location."""
    resolved = path.resolve()
    for tier_name, tier_path in TIER_PATHS.items():
        try:
            resolved.relative_to(tier_path.resolve())
            return MemoryTier(tier_name)
        except ValueError:
            continue
    # Default: anything under vault/ not otherwise classified
    return MemoryTier.SEMANTIC


def make_chunk_id(source_path: str, header_path: str, index: int) -> str:
    """Deterministic sha256[:16] chunk ID for stable upsert."""
    key = f"{source_path}::{header_path}::{index}"
    return hashlib.sha256(key.encode()).hexdigest()[:16]


def chunk_markdown(file_path: Path) -> list[VaultChunk]:
    """Split a markdown file at H1/H2/H3 boundaries into VaultChunks."""
    text = file_path.read_text(encoding="utf-8")
    source_path = _normalize_path(file_path)
    tier = classify_tier(file_path)
    mtime = datetime.fromtimestamp(file_path.stat().st_mtime, tz=timezone.utc).isoformat()

    # Find all H1/H2/H3 headings and their positions
    headings: list[tuple[int, int, str]] = []  # (pos, level, title)
    for m in _HEADING_RE.finditer(text):
        level = len(m.group(1))
        title = m.group(2).strip()
        headings.append((m.start(), level, title))

    # Build sections: text between consecutive headings
    sections: list[tuple[str, str]] = []  # (header_path, content)
    if not headings:
        # No headings — entire file is one chunk
        sections.append(("(root)", text.strip()))
    else:
        # Preamble before first heading
        preamble = text[: headings[0][0]].strip()
        if preamble:
            sections.append(("(preamble)", preamble))

        # Track heading hierarchy for header_path
        stack: list[str] = []  # current hierarchy
        stack_levels: list[int] = []

        for i, (pos, level, title) in enumerate(headings):
            # Update stack to reflect current heading hierarchy
            while stack_levels and stack_levels[-1] >= level:
                stack.pop()
                stack_levels.pop()
            stack.append(title)
            stack_levels.append(level)

            header_path = " > ".join(stack)

            # Content = text from after this heading line to next heading (or EOF)
            # Find end of heading line
            line_end = text.find("\n", pos)
            if line_end == -1:
                content_start = len(text)
            else:
                content_start = line_end + 1

            if i + 1 < len(headings):
                content_end = headings[i + 1][0]
            else:
                content_end = len(text)

            content = text[content_start:content_end].strip()
            sections.append((header_path, content))

    # Convert sections to VaultChunks, skipping empties
    chunks: list[VaultChunk] = []
    for idx, (header_path, content) in enumerate(sections):
        # Skip near-empty chunks
        stripped = re.sub(r"<!--.*?-->", "", content, flags=re.DOTALL).strip()
        if len(stripped) < _MIN_CHUNK_CHARS:
            continue

        chunk = VaultChunk(
            chunk_id=make_chunk_id(source_path, header_path, idx),
            source_path=source_path,
            tier=tier,
            header_path=header_path,
            content=content,
            file_mtime=mtime,
        )
        chunks.append(chunk)

        # Warn on oversized chunks (rough estimate: 1 token ≈ 4 chars)
        if len(content) / 4 > _WARN_CHUNK_TOKENS:
            log.warning(
                "Large chunk (~%d tokens): %s [%s]",
                len(content) // 4,
                source_path,
                header_path,
            )

    return chunks


def discover_vault_files() -> list[Path]:
    """Find all markdown files across all tier directories."""
    files: list[Path] = []
    for tier_path in TIER_PATHS.values():
        if not tier_path.exists():
            continue
        for md in tier_path.rglob("*.md"):
            if md.name in _SKIP_FILENAMES:
                continue
            files.append(md)
    return sorted(files)
