"""Identity bootstrapping — create initial vault identity files."""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from pathlib import Path

from core.interface.config import VAULT_DIR

log = logging.getLogger(__name__)

_SAFE_TEXT_RE = re.compile(r"[^\w\s.,!?'\"()\-/@#&+]", re.UNICODE)


def bootstrap_identity(name: str, description: str = "", vault_dir: Path | None = None) -> dict:
    """Create identity vault files for a new user. Returns dict of created files."""
    name = name.strip()
    if not name:
        raise ValueError("Name is required")
    if len(name) > 64:
        raise ValueError("Name must be 64 characters or fewer")
    # Sanitize to prevent YAML frontmatter injection
    name = name.replace("---", "").replace("\n", " ").strip()
    description = description.replace("---", "").replace("\n", " ").strip() if description else ""

    vault = vault_dir or VAULT_DIR
    identity_dir = vault / "identity"
    identity_dir.mkdir(parents=True, exist_ok=True)
    created = {}
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # IDENTITY.md
    identity_file = identity_dir / "IDENTITY.md"
    if not identity_file.exists():
        desc_block = f"\n{description}\n" if description.strip() else ""
        content = f"""---
tier: CORE
domain: IDENTITY
status: ACTIVE
updated: {today}
tags: [identity, core]
---

# Identity

Name: {name}
{desc_block}"""
        identity_file.write_text(content.strip() + "\n", encoding="utf-8")
        created["identity"] = str(identity_file)
        log.info("Created identity file: %s", identity_file.name)

    # MISSION.md template
    mission_file = identity_dir / "MISSION.md"
    if not mission_file.exists():
        mission_content = f"""---
tier: CORE
domain: IDENTITY
status: ACTIVE
updated: {today}
tags: [identity, mission]
---

# Mission

What are you building? What matters to you? Edit this file to tell your AI what you're working toward.
"""
        mission_file.write_text(mission_content.strip() + "\n", encoding="utf-8")
        created["mission"] = str(mission_file)

    # Trigger vault reindex so identity is immediately searchable
    if created:
        try:
            from core.memory.indexer import index_vault
            index_vault(full_rebuild=False)
        except Exception:
            log.warning("Failed to reindex vault after identity creation")

    return created
