"""Research reviewer — list, approve, reject staged research results."""

from __future__ import annotations

import re
import shutil
from pathlib import Path

from core.framework.validation import validate_filename
from core.interface.config import TIER_PATHS
from core.memory.indexer import index_vault

_STAGING_DIR = Path("staging/research")
_REQUIRED_FRONTMATTER = {"topic", "tier", "domain", "status", "updated"}
_ALLOWED_RESEARCH_TIERS = {"semantic", "procedural"}


def _parse_frontmatter(text: str) -> dict | None:
    match = re.match(r"^---\s*\n(.*?)\n---", text, re.DOTALL)
    if not match:
        return None
    try:
        import yaml
        return yaml.safe_load(match.group(1)) or {}
    except Exception:
        return None


class ResearchReviewer:
    def __init__(self, staging_dir: Path | None = None):
        self._staging_dir = staging_dir or _STAGING_DIR

    def list_staged(self) -> dict:
        if not self._staging_dir.exists():
            return {"staged": [], "count": 0}
        staged = []
        for f in sorted(self._staging_dir.glob("*.md")):
            text = f.read_text(encoding="utf-8", errors="replace")
            fm = _parse_frontmatter(text) or {}
            body = re.sub(r"^---.*?---\s*", "", text, flags=re.DOTALL).strip()
            staged.append({
                "filename": f.name,
                "topic": fm.get("topic", "unknown"),
                "sources": fm.get("sources", []),
                "summary_preview": body[:200],
                "created": fm.get("created", "unknown"),
            })
        return {"staged": staged, "count": len(staged)}

    def approve(self, filename: str, vault_tier: str = "semantic", domain: str = "RESEARCH") -> dict:
        try:
            validate_filename(filename)
        except ValueError as exc:
            return {"status": "error", "message": str(exc)}
        if vault_tier not in _ALLOWED_RESEARCH_TIERS:
            return {"status": "error", "message": f"Research may only promote to: {sorted(_ALLOWED_RESEARCH_TIERS)}"}
        source = self._staging_dir / filename
        if not source.exists():
            return {"status": "error", "message": f"File not found: {filename}"}

        text = source.read_text(encoding="utf-8")
        fm = _parse_frontmatter(text)
        if fm is None:
            return {"status": "error", "message": "No valid frontmatter found"}
        missing = _REQUIRED_FRONTMATTER - set(fm.keys())
        if missing:
            return {"status": "error", "message": f"Frontmatter missing: {sorted(missing)}"}

        dest_dir = TIER_PATHS[vault_tier]
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / filename
        shutil.copy2(source, dest)
        source.unlink()
        index_vault(full_rebuild=False)

        return {"status": "approved", "source": str(source), "destination": str(dest), "tier": vault_tier}

    def reject(self, filename: str) -> dict:
        try:
            validate_filename(filename)
        except ValueError as exc:
            return {"status": "error", "message": str(exc)}
        target = self._staging_dir / filename
        if not target.exists():
            return {"status": "error", "message": f"File not found: {filename}"}
        target.unlink()
        return {"rejected": [filename], "count": 1}

    def reject_all(self) -> dict:
        if not self._staging_dir.exists():
            return {"rejected": [], "count": 0}
        rejected = []
        for f in self._staging_dir.glob("*.md"):
            f.unlink()
            rejected.append(f.name)
        return {"rejected": rejected, "count": len(rejected)}
