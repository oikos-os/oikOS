"""Vault freshness monitor — scans vault files for stale frontmatter dates."""

from __future__ import annotations

import re
from datetime import date, datetime
from pathlib import Path

from core.interface.config import VAULT_DIR

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---", re.DOTALL)
_UPDATED_RE = re.compile(r"^updated:\s*(.+)$", re.MULTILINE)
_STATUS_RE = re.compile(r"^status:\s*(.+)$", re.MULTILINE)

STALE_THRESHOLD_DAYS = 14


def scan_vault(vault_dir: Path | None = None) -> dict:
    """Scan vault .md files and return freshness report."""
    vault_dir = vault_dir or VAULT_DIR
    today = date.today()
    stale = []
    missing_fm = []
    current = []

    for md in sorted(vault_dir.rglob("*.md")):
        if any("backup" in p for p in md.relative_to(vault_dir).parts):
            continue
        text = md.read_text(encoding="utf-8", errors="replace")
        fm_match = _FRONTMATTER_RE.match(text)
        if not fm_match:
            missing_fm.append(str(md.relative_to(vault_dir)))
            continue

        fm = fm_match.group(1)
        status_match = _STATUS_RE.search(fm)
        status = (status_match.group(1).strip().upper() if status_match else "UNKNOWN")
        if status != "ACTIVE":
            continue

        updated_match = _UPDATED_RE.search(fm)
        if not updated_match:
            missing_fm.append(str(md.relative_to(vault_dir)))
            continue

        try:
            updated_date = datetime.strptime(
                updated_match.group(1).strip(), "%Y-%m-%d"
            ).date()
        except ValueError:
            missing_fm.append(str(md.relative_to(vault_dir)))
            continue

        days_old = (today - updated_date).days
        rel = str(md.relative_to(vault_dir))
        if days_old > STALE_THRESHOLD_DAYS:
            stale.append({"file": rel, "updated": str(updated_date), "days": days_old})
        else:
            current.append(rel)

    return {
        "stale": len(stale),
        "stale_files": stale,
        "missing_frontmatter": len(missing_fm),
        "missing_files": missing_fm,
        "current": len(current),
        "total_active": len(current) + len(stale),
        "date": str(today),
    }


def format_report(result: dict) -> str:
    """Format scan result as markdown report."""
    lines = [
        "# VAULT FRESHNESS REPORT",
        f"**Generated:** {result['date']}",
        f"**Vault:** {VAULT_DIR}",
        "",
        "## STALE FILES (active, updated > 14 days ago)",
    ]
    if result["stale_files"]:
        lines.append("| File | Last Updated | Days Stale |")
        lines.append("|---|---|---|")
        for f in result["stale_files"]:
            lines.append(f"| {f['file']} | {f['updated']} | {f['days']} |")
    else:
        lines.append("(none)")

    lines.extend(["", "## MISSING FRONTMATTER"])
    if result["missing_files"]:
        lines.append("| File |")
        lines.append("|---|")
        for f in result["missing_files"]:
            lines.append(f"| {f} |")
    else:
        lines.append("(none)")

    lines.extend([
        "",
        "## SUMMARY",
        f"Total active files: {result['total_active']} | "
        f"Current (<14d): {result['current']} | "
        f"Stale: {result['stale']} | "
        f"Missing frontmatter: {result['missing_frontmatter']}",
    ])
    return "\n".join(lines)


def run(console=None) -> dict:
    """Run vault freshness scan and print results."""
    result = scan_vault()
    report = format_report(result)
    if console:
        console.print(report)
    return result
