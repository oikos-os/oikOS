"""Vault tools — search, compile, index, ingest, and stats for the oikOS vault."""

from datetime import datetime, timezone
from pathlib import Path

from core.framework import oikos_tool, PrivacyTier, AutonomyLevel


@oikos_tool(
    name="oikos_vault_search",
    description="Search the oikOS vault via hybrid BM25+vector search",
    privacy=PrivacyTier.NEVER_LEAVE,
    autonomy=AutonomyLevel.SAFE,
    toolset="vault",
)
def vault_search(query: str, limit: int = 5) -> list[dict]:
    from core.memory.search import hybrid_search
    results = hybrid_search(query, limit=limit)
    return [
        {
            "header": r.header_path,
            "source": r.source_path,
            "tier": r.tier.value if hasattr(r.tier, "value") else str(r.tier),
            "score": round(r.final_score, 4),
            "snippet": r.content[:200],
        }
        for r in results
    ]


@oikos_tool(
    name="oikos_vault_compile",
    description="Compile a context window from vault content within a token budget",
    privacy=PrivacyTier.NEVER_LEAVE,
    autonomy=AutonomyLevel.SAFE,
    toolset="vault",
)
def vault_compile(query: str, token_budget: int = 6000) -> dict:
    from core.cognition.compiler import compile_context, render_context
    compiled = compile_context(query, token_budget=token_budget)
    return {
        "query": compiled.query,
        "total_tokens": compiled.total_tokens,
        "budget": compiled.budget,
        "slices": len(compiled.slices),
        "rendered": render_context(compiled)[:2000],
    }


@oikos_tool(
    name="oikos_vault_index",
    description="Rebuild the vault search index (incremental or full rebuild requires approval)",
    privacy=PrivacyTier.NEVER_LEAVE,
    autonomy=AutonomyLevel.ASK_FIRST,
    toolset="vault",
)
def vault_index(full_rebuild: bool = False) -> dict:
    from core.memory.indexer import index_vault
    return index_vault(full_rebuild=full_rebuild)


_REQUIRED_FRONTMATTER = {"tier", "domain", "status", "updated"}
_TIER_DIR_MAP = {
    "core": "identity",
    "semantic": "knowledge",
    "procedural": "patterns",
}


def _parse_frontmatter(text: str) -> dict | None:
    """Return frontmatter dict if valid YAML block exists, else None."""
    import re
    match = re.match(r"^---\s*\n(.*?)\n---", text, re.DOTALL)
    if not match:
        return None
    try:
        import yaml
        return yaml.safe_load(match.group(1)) or {}
    except Exception:
        return None


@oikos_tool(
    name="oikos_vault_ingest",
    description="Ingest a file into the vault with frontmatter validation and indexing",
    privacy=PrivacyTier.NEVER_LEAVE,
    autonomy=AutonomyLevel.ASK_FIRST,
    toolset="vault",
)
def vault_ingest(source_path: str, vault_tier: str = "semantic", domain: str = "GENERAL") -> dict:
    from core.interface.config import TIER_PATHS, FILE_AGENT_ALLOWED_PATHS

    src = Path(source_path).resolve()

    # Scope validation — only read from allowed paths
    from core.agency.file_agent import _PROHIBITED_PATHS_DEFAULT
    for prohibited in _PROHIBITED_PATHS_DEFAULT:
        if src.is_relative_to(Path(prohibited).resolve()):
            return {"status": "error", "message": f"PROHIBITED source path"}
    allowed = False
    for allowed_path in FILE_AGENT_ALLOWED_PATHS:
        if src.is_relative_to(Path(allowed_path).resolve()):
            allowed = True
            break
    if not allowed:
        return {"status": "error", "message": "Source path outside allowed scope"}

    if not src.exists():
        return {"status": "error", "message": f"Source not found: {source_path}"}
    if not src.is_file():
        return {"status": "error", "message": f"Not a file: {source_path}"}

    text = src.read_text(encoding="utf-8", errors="replace")
    fm = _parse_frontmatter(text)

    if fm is None:
        return {
            "status": "error",
            "message": "No frontmatter found. File must start with a YAML block between --- markers.",
            "required_fields": sorted(_REQUIRED_FRONTMATTER),
        }

    missing = _REQUIRED_FRONTMATTER - set(fm.keys())
    if missing:
        return {
            "status": "error",
            "message": f"Frontmatter missing required fields: {sorted(missing)}",
            "required_fields": sorted(_REQUIRED_FRONTMATTER),
            "found_fields": sorted(fm.keys()),
        }

    tier_key = vault_tier.lower()
    if tier_key not in TIER_PATHS:
        return {"status": "error", "message": f"Unknown vault_tier '{vault_tier}'. Use: {list(TIER_PATHS)}"}

    dest_dir = TIER_PATHS[tier_key]
    dest = dest_dir / src.name

    from core.agency.approval import ApprovalQueue
    queue = ApprovalQueue()
    proposal = queue.propose(
        action_type="vault_ingest",
        tool_name="oikos_vault_ingest",
        reason=f"Ingest {src.name} into vault/{_TIER_DIR_MAP.get(tier_key, tier_key)}",
        estimated_tokens=0,
        tool_args={"source": str(src), "destination": str(dest), "tier": vault_tier, "domain": domain},
    )

    return {
        "status": "proposal_created",
        "proposal_id": proposal.proposal_id,
        "source": str(src),
        "destination": str(dest),
        "tier": vault_tier,
        "domain": domain,
    }


@oikos_tool(
    name="oikos_vault_stats",
    description="Get vault health metrics: file count, tier distribution, stale files, index coverage",
    privacy=PrivacyTier.NEVER_LEAVE,
    autonomy=AutonomyLevel.SAFE,
    toolset="vault",
)
def vault_stats() -> dict:
    from core.interface.config import VAULT_DIR, LANCEDB_DIR

    now = datetime.now(tz=timezone.utc).timestamp()
    stale_threshold = 30 * 24 * 3600  # 30 days in seconds

    tier_dirs = {
        "core": VAULT_DIR / "identity",
        "semantic": VAULT_DIR / "knowledge",
        "procedural": VAULT_DIR / "patterns",
    }

    by_tier: dict[str, int] = {}
    stale_files: list[str] = []
    orphan_files: list[str] = []

    for tier_name, tier_path in tier_dirs.items():
        if not tier_path.exists():
            by_tier[tier_name] = 0
            continue
        md_files = list(tier_path.glob("*.md"))
        by_tier[tier_name] = len(md_files)
        for f in md_files:
            if now - f.stat().st_mtime > stale_threshold:
                stale_files.append(str(f))
            text = f.read_text(encoding="utf-8", errors="replace")
            if _parse_frontmatter(text) is None:
                orphan_files.append(str(f))

    total = sum(by_tier.values())

    # LanceDB index coverage
    index_tables: list[dict] = []
    if LANCEDB_DIR.exists():
        try:
            import lancedb
            db = lancedb.connect(str(LANCEDB_DIR))
            for table_name in db.table_names():
                try:
                    tbl = db.open_table(table_name)
                    index_tables.append({"table": table_name, "rows": tbl.count_rows()})
                except Exception:
                    index_tables.append({"table": table_name, "rows": "unknown"})
        except Exception:
            index_tables = [{"table": "error", "rows": "lancedb unavailable"}]

    return {
        "total_files": total,
        "by_tier": by_tier,
        "stale_files": stale_files,
        "orphan_files": orphan_files,
        "index_tables": index_tables,
    }
