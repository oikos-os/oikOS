"""LanceDB table management — create, ingest, re-index, FTS."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

import pyarrow as pa

import lancedb

from core.memory.chunker import chunk_markdown, discover_vault_files
from core.interface.config import EMBED_DIMS, LANCEDB_DIR, TABLE_NAME
from core.memory.embedder import embed_batch
from core.interface.models import VaultChunk

log = logging.getLogger(__name__)

# ── PyArrow schema (explicit, not LanceModel) ─────────────────────────
SCHEMA = pa.schema(
    [
        pa.field("chunk_id", pa.string()),
        pa.field("source_path", pa.string()),
        pa.field("tier", pa.string()),
        pa.field("header_path", pa.string()),
        pa.field("content", pa.string()),
        pa.field("file_mtime", pa.string()),
        pa.field("tags", pa.string()),
        pa.field("indexed_at", pa.string()),
        pa.field("vector", pa.list_(pa.float32(), EMBED_DIMS)),
    ]
)


def get_db() -> lancedb.db.DBConnection:
    LANCEDB_DIR.mkdir(parents=True, exist_ok=True)
    return lancedb.connect(str(LANCEDB_DIR))


def _table_exists(db: lancedb.db.DBConnection, name: str) -> bool:
    """Check if a table exists (handles list_tables response object)."""
    resp = db.list_tables()
    names = resp.tables if hasattr(resp, "tables") else list(resp)
    return name in names


def get_or_create_table() -> lancedb.table.LanceTable:
    db = get_db()
    if _table_exists(db, TABLE_NAME):
        return db.open_table(TABLE_NAME)
    return db.create_table(TABLE_NAME, schema=SCHEMA)


def chunks_to_records(chunks: list[VaultChunk]) -> list[dict]:
    """Embed chunks and return LanceDB-ready dicts."""
    if not chunks:
        return []
    texts = [c.content for c in chunks]
    vectors = embed_batch(texts)
    now = datetime.now(timezone.utc).isoformat()
    records = []
    for chunk, vec in zip(chunks, vectors):
        records.append(
            {
                "chunk_id": chunk.chunk_id,
                "source_path": chunk.source_path,
                "tier": chunk.tier.value,
                "header_path": chunk.header_path,
                "content": chunk.content,
                "file_mtime": chunk.file_mtime,
                "tags": json.dumps(chunk.tags),
                "indexed_at": now,
                "vector": vec,
            }
        )
    return records


def _get_indexed_files(table: lancedb.table.LanceTable) -> dict[str, str]:
    """Return {source_path: max(file_mtime)} from the index."""
    try:
        df = table.to_arrow().select(["source_path", "file_mtime"])
        result: dict[str, str] = {}
        for path, mtime in zip(
            df.column("source_path").to_pylist(),
            df.column("file_mtime").to_pylist(),
        ):
            if path not in result or mtime > result[path]:
                result[path] = mtime
        return result
    except Exception:
        return {}


def _rebuild_fts(table: lancedb.table.LanceTable) -> None:
    """Rebuild the full-text search index on content."""
    try:
        table.create_fts_index("content", replace=True)
    except Exception as e:
        log.warning("FTS index rebuild failed: %s", e)


def index_vault(full_rebuild: bool = False) -> dict:
    """Index vault markdown files into LanceDB.

    Returns stats dict with counts.
    """
    db = get_db()

    if full_rebuild and _table_exists(db, TABLE_NAME):
        db.drop_table(TABLE_NAME)

    table = get_or_create_table()

    # Discover all vault files
    vault_files = discover_vault_files()
    from core.memory.chunker import _normalize_path

    vault_paths = {_normalize_path(f) for f in vault_files}

    stats = {"added": 0, "skipped": 0, "deleted": 0, "files": len(vault_files)}

    if full_rebuild:
        # Full rebuild: chunk and embed everything
        all_chunks: list[VaultChunk] = []
        for f in vault_files:
            all_chunks.extend(chunk_markdown(f))

        if all_chunks:
            records = chunks_to_records(all_chunks)
            table.add(records)
            stats["added"] = len(records)

    else:
        # Incremental: compare mtimes
        indexed = _get_indexed_files(table)

        # Delete records for files that no longer exist
        stale_paths = set(indexed.keys()) - vault_paths
        for stale in stale_paths:
            table.delete(f"source_path = '{stale.replace(chr(39), chr(39)*2)}'")
            stats["deleted"] += 1

        # Process each vault file
        for f in vault_files:
            norm_path = _normalize_path(f)
            file_mtime = datetime.fromtimestamp(
                f.stat().st_mtime, tz=timezone.utc
            ).isoformat()

            if norm_path in indexed and indexed[norm_path] >= file_mtime:
                stats["skipped"] += 1
                continue

            # Delete old records for this file, then re-add
            if norm_path in indexed:
                table.delete(f"source_path = '{norm_path.replace(chr(39), chr(39)*2)}'")

            chunks = chunk_markdown(f)
            if chunks:
                records = chunks_to_records(chunks)
                table.add(records)
                stats["added"] += len(records)

    # Rebuild FTS after mutations
    if stats["added"] > 0 or stats["deleted"] > 0:
        _rebuild_fts(table)

    return stats


def get_table_stats() -> dict:
    """Return index statistics."""
    try:
        table = get_or_create_table()
        arrow = table.to_arrow()
        total = arrow.num_rows
        if total == 0:
            return {"total_rows": 0, "unique_files": 0, "tier_breakdown": {}}

        files = set(arrow.column("source_path").to_pylist())
        tiers = arrow.column("tier").to_pylist()
        tier_counts: dict[str, int] = {}
        for t in tiers:
            tier_counts[t] = tier_counts.get(t, 0) + 1

        return {
            "total_rows": total,
            "unique_files": len(files),
            "tier_breakdown": tier_counts,
        }
    except Exception:
        return {"total_rows": 0, "unique_files": 0, "tier_breakdown": {}}
