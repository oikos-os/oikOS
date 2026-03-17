"""Sync manifest checker — detects drifted cross-platform files."""

from __future__ import annotations

import os
import re
from datetime import date, datetime
from pathlib import Path

_MANIFEST_PATH_DEFAULT = Path("D:/COMMAND/SYNC_MANIFEST.md")
_TABLE_ROW_RE = re.compile(
    r"\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*([^|]*?)\s*\|\s*(\d{4}-\d{2}-\d{2})\s*\|"
)


def parse_manifest(manifest_path: Path | None = None) -> list[dict]:
    """Parse the sync manifest markdown table into entries."""
    path = manifest_path or _MANIFEST_PATH_DEFAULT
    if not path.exists():
        return []

    text = path.read_text(encoding="utf-8", errors="replace")
    entries = []
    for m in _TABLE_ROW_RE.finditer(text):
        doc, primary, mirrors, synced = m.groups()
        if doc.strip().startswith("---") or doc.strip() == "Document":
            continue
        entries.append({
            "document": doc.strip(),
            "primary": primary.strip(),
            "mirrors": mirrors.strip(),
            "last_synced": synced.strip(),
        })
    return entries


def _resolve_path(location: str) -> Path | None:
    """Try to resolve a location string to a filesystem path."""
    if "Claude Project" in location or location == "\u2014" or location.strip() == "\u2014":
        return None
    if "GitHub" in location:
        return None
    p = Path(location)
    if p.is_absolute():
        return p
    return None


def check_sync(manifest_path: Path | None = None) -> dict:
    """Check all manifest entries for drift."""
    entries = parse_manifest(manifest_path)
    today = date.today()
    needs_update = []
    cloud_staleness = []
    all_current = []

    for entry in entries:
        synced = datetime.strptime(entry["last_synced"], "%Y-%m-%d").date()
        days_ago = (today - synced).days

        path = _resolve_path(entry["primary"])
        if path and path.exists():
            mtime = datetime.fromtimestamp(os.path.getmtime(path)).date()
            if mtime > synced:
                needs_update.append({
                    "document": entry["document"],
                    "modified": str(mtime),
                    "synced": entry["last_synced"],
                    "mirrors": entry["mirrors"],
                })
                continue

        if "Claude Project" in entry["primary"]:
            cloud_staleness.append({
                "document": entry["document"],
                "project": entry["primary"],
                "days_ago": days_ago,
            })
            continue

        all_current.append({
            "document": entry["document"],
            "synced": entry["last_synced"],
        })

    return {
        "needs_update": needs_update,
        "cloud_staleness": cloud_staleness,
        "all_current": all_current,
        "date": str(today),
    }


def format_report(result: dict) -> str:
    """Format sync check result for console output."""
    lines = [f"SYNC STATUS \u2014 {result['date']}", ""]

    if result["needs_update"]:
        lines.append("NEEDS UPDATE:")
        for item in result["needs_update"]:
            lines.append(
                f"  x {item['document']} \u2014 modified {item['modified']}, "
                f"last synced {item['synced']}"
            )
            if item["mirrors"] and item["mirrors"] != "\u2014":
                lines.append(f"    -> ACTION: Update mirrors at {item['mirrors']}")
        lines.append("")

    if result["cloud_staleness"]:
        lines.append("CLAUDE PROJECT STALENESS:")
        for item in result["cloud_staleness"]:
            lines.append(
                f"  {item['document']} \u2014 {item['project']} \u2014 "
                f"synced {item['days_ago']} days ago"
            )
        lines.append("")

    if result["all_current"]:
        lines.append("ALL CURRENT:")
        for item in result["all_current"]:
            lines.append(f"  + {item['document']} \u2014 current ({item['synced']})")

    return "\n".join(lines)


def run(console=None, manifest_path: Path | None = None) -> dict:
    """Run sync check and print results."""
    result = check_sync(manifest_path)
    report = format_report(result)
    if console:
        console.print(report)
    return result
