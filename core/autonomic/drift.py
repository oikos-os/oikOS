"""Drift Detector — three-tier escalation nudge generation (Phase 5.7 → 6a.2)."""

from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from core.interface.config import (
    ESCALATION_ADVISORY_DAYS,
    ESCALATION_DECAY_THRESHOLD,
    ESCALATION_INTERVENTION_DAYS,
    ESCALATION_STATE_FILE,
    LOGS_DIR,
    VAULT_DIR,
)
from core.interface.models import DriftNudge, EscalationTier

log = logging.getLogger(__name__)

# How close a deadline must be to trigger (days)
DEADLINE_HORIZON_DAYS = 14
# How many days of inactivity on a project triggers a nudge
INACTIVITY_THRESHOLD_DAYS = 3


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _parse_deadline(date_str: str, year: int | None = None) -> datetime | None:
    """Parse a date string like 'Feb 27', 'Mar 27', 'Apr 24', 'Jan 30'."""
    if year is None:
        year = _utcnow().year

    for fmt in ("%b %d", "%B %d"):
        try:
            dt = datetime.strptime(date_str.strip(), fmt).replace(
                year=year, tzinfo=timezone.utc
            )
            return dt
        except ValueError:
            continue
    return None


def parse_goals_deadlines(goals_path: Path | None = None) -> list[dict]:
    """Extract deadlines from GOALS.md tactical timeline table.

    Returns list of {project, track, date_str, status, deadline} dicts.
    """
    goals_path = goals_path or (VAULT_DIR / "identity" / "GOALS.md")
    if not goals_path.exists():
        return []

    text = goals_path.read_text(encoding="utf-8")
    deadlines = []

    # Match table rows: | **Date** | Artist | *Track* | **STATUS** | ... |
    for match in re.finditer(
        r"\|\s*\*\*([^*]+)\*\*\s*\|\s*([^|]+)\|\s*\*([^*]+)\*\s*\|\s*\*\*([^*]+)\*\*\s*\|",
        text,
    ):
        date_str, artist, track, status = (
            match.group(1).strip(),
            match.group(2).strip(),
            match.group(3).strip(),
            match.group(4).strip(),
        )

        deadline = _parse_deadline(date_str)
        if deadline is None:
            continue

        deadlines.append({
            "project": artist.strip(),
            "track": track.strip(),
            "date_str": date_str,
            "status": status,
            "deadline": deadline,
        })

    return deadlines


def parse_projects(projects_path: Path | None = None) -> list[dict]:
    """Extract project names, domain tags, and keywords from PROJECTS.md.

    Each project header like '## 1. PROJECT EXAMPLE PROJECT (THE LABEL)'
    yields {name, name_lower, keywords} where keywords are the lowercase
    words from the project name (used for domain matching in session logs).
    """
    projects_path = projects_path or (VAULT_DIR / "identity" / "PROJECTS.md")
    if not projects_path.exists():
        return []

    text = projects_path.read_text(encoding="utf-8")
    projects = []

    for match in re.finditer(r"^## \d+\.\s+PROJECT\s+(.+?)(?:\s*\(.+\))?\s*$", text, re.MULTILINE):
        name = match.group(1).strip()
        # Generate keywords from project name words (>2 chars)
        keywords = {w.lower() for w in name.split() if len(w) > 2}
        projects.append({"name": name, "name_lower": name.lower(), "keywords": keywords})

    return projects


def _build_domain_keyword_map(projects_path: Path | None = None) -> dict[str, set[str]]:
    """Build domain -> keyword set mapping from PROJECTS.md.

    Returns e.g. {"example project": {"trendy", "decay"}, "oikos": {"oikos"}, ...}
    Falls back to a minimal default if PROJECTS.md is unavailable.
    """
    projects = parse_projects(projects_path)
    domain_map: dict[str, set[str]] = {}

    for p in projects:
        domain = p["name_lower"]
        domain_map[domain] = p["keywords"]

    # Always include "oikos" for KP-CLAUDE/KP-GEM session detection
    if "oikos" not in domain_map:
        domain_map["oikos"] = {"oikos"}

    return domain_map


def _infer_domain_for_deadline(deadline: dict, domain_map: dict[str, set[str]]) -> str | None:
    """Infer which domain a deadline belongs to based on its artist/project field.

    Checks if the artist name or track name matches any domain keywords.
    Falls back to checking if the deadline lives under a known section header.
    """
    artist_lower = deadline["project"].lower()
    track_lower = deadline["track"].lower()

    for domain, keywords in domain_map.items():
        # Direct artist match (e.g. "USER" in example project keywords)
        if any(kw in artist_lower for kw in keywords):
            return domain
        # Track match (e.g. "Horas" matches "horas" keyword)
        if any(kw in track_lower for kw in keywords):
            return domain

    # If no keyword match, default: music-related deadlines map to the first music-like domain
    # (all current GOALS.md deadlines are release dates )
    for domain in domain_map:
        if any(kw in domain for kw in ("trendy", "music", "decay", "label")):
            return domain

    return None


def get_session_activity(
    days: int = 14,
    domain_map: dict[str, set[str]] | None = None,
) -> list[dict]:
    """Scan session logs and interaction logs for recent activity.

    Domain hints are derived from PROJECTS.md keywords (externalized, not hardcoded).
    Returns list of {date, source, domain_hints} dicts.
    """
    if domain_map is None:
        domain_map = _build_domain_keyword_map()

    cutoff = _utcnow() - timedelta(days=days)
    activity = []

    if not LOGS_DIR.exists():
        return activity

    def _extract_hints(text_lower: str) -> set[str]:
        """Match text against all domain keywords."""
        hints: set[str] = set()
        for domain, keywords in domain_map.items():
            if any(kw in text_lower for kw in keywords):
                hints.add(domain)
        return hints

    # Scan markdown session logs
    for f in LOGS_DIR.glob("*.md"):
        try:
            date_str = f.stem[:10]
            dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            if dt < cutoff:
                continue

            hints = set()
            name_lower = f.stem.lower()
            if "claude" in name_lower or "gem" in name_lower:
                hints.add("oikos")

            content_lower = f.read_text(encoding="utf-8", errors="replace").lower()
            hints |= _extract_hints(content_lower)

            activity.append({"date": dt, "source": f.name, "domain_hints": hints})
        except (ValueError, OSError):
            continue

    # Scan JSONL interaction logs
    for f in LOGS_DIR.glob("*SESSION-*.jsonl"):
        try:
            date_str = f.stem[:10]
            dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            if dt < cutoff:
                continue

            hints = {"oikos"}  # interaction logs are always OIKOS sessions
            for line in f.read_text(encoding="utf-8", errors="replace").strip().split("\n"):
                if not line.strip():
                    continue
                try:
                    entry = json.loads(line)
                    q = entry.get("query", "").lower()
                    hints |= _extract_hints(q)
                except json.JSONDecodeError:
                    continue

            activity.append({"date": dt, "source": f.name, "domain_hints": hints})
        except (ValueError, OSError):
            continue

    return sorted(activity, key=lambda a: a["date"], reverse=True)


def _days_since_domain_activity(activity: list[dict], domain: str) -> int | None:
    """Find how many days since the last session touching this domain."""
    now = _utcnow()
    for a in activity:
        if domain.lower() in {h.lower() for h in a["domain_hints"]}:
            return (now - a["date"]).days
    return None


def _recent_domain_focus(activity: list[dict], last_n: int = 3) -> list[str]:
    """What domains have the last N sessions focused on."""
    domains: list[str] = []
    for a in activity[:last_n]:
        domains.extend(a["domain_hints"])
    return domains


# ── Escalation state ────────────────────────────────────────────────


def _pattern_id(domain: str, track: str) -> str:
    """Deterministic pattern ID for dismissal tracking."""
    return hashlib.sha256(f"{domain}:{track}".encode()).hexdigest()[:16]


def _load_escalation_state(state_file: Path | None = None) -> dict:
    """Load logs/escalation/state.json (dismissals tracker)."""
    path = state_file or ESCALATION_STATE_FILE
    if not path.exists():
        return {"patterns": {}}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"patterns": {}}


def _save_escalation_state(state: dict, state_file: Path | None = None) -> None:
    """Persist escalation state."""
    path = state_file or ESCALATION_STATE_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2), encoding="utf-8")


def record_dismissal(pattern_id: str, reason: str | None = None, state_file: Path | None = None) -> None:
    """Record nudge dismissal. Increment counter. Track unreasoned count."""
    state = _load_escalation_state(state_file)
    patterns = state.setdefault("patterns", {})
    entry = patterns.setdefault(pattern_id, {
        "times_surfaced": 0,
        "times_dismissed": 0,
        "unreasoned_dismissals": 0,
        "last_reason": None,
        "suppressed": False,
    })
    entry["times_dismissed"] += 1
    if reason:
        entry["last_reason"] = reason
    else:
        entry["unreasoned_dismissals"] += 1

    if entry["unreasoned_dismissals"] >= ESCALATION_DECAY_THRESHOLD:
        entry["suppressed"] = True

    _save_escalation_state(state, state_file)


def is_suppressed(pattern_id: str, state_file: Path | None = None) -> bool:
    """True if pattern has >= ESCALATION_DECAY_THRESHOLD unreasoned dismissals."""
    state = _load_escalation_state(state_file)
    entry = state.get("patterns", {}).get(pattern_id, {})
    return entry.get("suppressed", False)


def _find_failure_pattern(domain: str, vault_dir: Path | None = None) -> str | None:
    """Search LEARNED.md and CHALLENGES.md for domain-related failure patterns."""
    vault = vault_dir or VAULT_DIR
    failure_words = {"fail", "stall", "delay", "abandon", "block", "stuck", "procrastinat"}
    domain_words = {w.lower() for w in domain.split() if len(w) > 2}

    for filename in ("LEARNED.md", "CHALLENGES.md"):
        path = vault / "identity" / filename
        if not path.exists():
            continue
        content = path.read_text(encoding="utf-8", errors="replace").lower()
        has_domain = any(w in content for w in domain_words)
        has_failure = any(w in content for w in failure_words)
        if has_domain and has_failure:
            # Extract a short context snippet
            for line in content.split("\n"):
                if any(w in line for w in domain_words) and any(w in line for w in failure_words):
                    return line.strip()[:120]
            return f"Pattern match in {filename} for domain '{domain}'"
    return None


# ── Nudge generation ────────────────────────────────────────────────


def generate_nudges(
    vault_dir: Path | None = None,
    state_file: Path | None = None,
) -> list[DriftNudge]:
    """Generate drift-detection nudges with three-tier escalation.

    Returns list of DriftNudge (may be empty if no drift detected).
    """
    nudges: list[DriftNudge] = []
    now = _utcnow()

    deadlines = parse_goals_deadlines()
    domain_map = _build_domain_keyword_map()
    activity = get_session_activity(domain_map=domain_map)
    recent_focus = _recent_domain_focus(activity)
    esc_state = _load_escalation_state(state_file)

    for dl in deadlines:
        # Skip released/completed items
        if dl["status"].upper() in ("RELEASED", "COMPLETE", "DONE"):
            continue

        days_until = (dl["deadline"] - now).days
        if days_until < 0 or days_until > DEADLINE_HORIZON_DAYS:
            continue

        # Infer which domain this deadline belongs to
        domain = _infer_domain_for_deadline(dl, domain_map)
        if domain is None:
            continue

        days_inactive = _days_since_domain_activity(activity, domain)

        # None = no activity at all in tracked window (worse than threshold)
        if days_inactive is None or days_inactive > INACTIVITY_THRESHOLD_DAYS:
            pid = _pattern_id(domain, dl["track"])

            # Check suppression
            if is_suppressed(pid, state_file):
                continue

            # Determine tier — time-based can skip tiers, dismissal-based promotes one step
            tier = EscalationTier.NUDGE
            pattern_match = None

            pattern_entry = esc_state.get("patterns", {}).get(pid, {})
            dismissed_count = pattern_entry.get("times_dismissed", 0)
            unreasoned_count = pattern_entry.get("unreasoned_dismissals", 0)

            effective_inactive = days_inactive if days_inactive is not None else 999

            # Time-based escalation (can skip tiers — severity justifies it)
            if effective_inactive >= ESCALATION_INTERVENTION_DAYS:
                tier = EscalationTier.INTERVENTION
            elif effective_inactive >= ESCALATION_ADVISORY_DAYS:
                pattern_match = _find_failure_pattern(domain, vault_dir)
                if pattern_match:
                    tier = EscalationTier.ADVISORY

            # Dismissal-based escalation (progressive — promotes one tier up only)
            if unreasoned_count >= 2:
                if tier == EscalationTier.NUDGE:
                    tier = EscalationTier.ADVISORY
                elif tier == EscalationTier.ADVISORY:
                    tier = EscalationTier.INTERVENTION

            dominant = [d for d in recent_focus if d != domain]
            dominant_str = ", ".join(set(dominant)) if dominant else "other domains"
            inactive_str = f"{days_inactive} days ago" if days_inactive is not None else "none found"

            message = (
                f"{dl['track']} deadline is {days_until} days out. "
                f"Last {domain} session: {inactive_str}. "
                f"Recent focus: {dominant_str}. "
                f"The Tinker may be winning."
            )

            if tier == EscalationTier.ADVISORY and pattern_match:
                message += f" [Pattern: {pattern_match}]"
            elif tier == EscalationTier.INTERVENTION:
                message += " INTERVENTION REQUIRED."

            # Track surfacing
            patterns = esc_state.setdefault("patterns", {})
            entry = patterns.setdefault(pid, {
                "times_surfaced": 0,
                "times_dismissed": 0,
                "unreasoned_dismissals": 0,
                "last_reason": None,
                "suppressed": False,
            })
            entry["times_surfaced"] += 1

            nudges.append(DriftNudge(
                message=message,
                tier=tier,
                domain=domain,
                pattern_id=pid,
            ))

    # Persist updated surfacing counts
    if nudges:
        _save_escalation_state(esc_state, state_file)

    return nudges


def drift_diagnostic() -> dict:
    """Return diagnostic info for oikos status: deadline count, domain map health."""
    deadlines = parse_goals_deadlines()
    domain_map = _build_domain_keyword_map()
    active_deadlines = [
        d for d in deadlines
        if d["status"].upper() not in ("RELEASED", "COMPLETE", "DONE")
    ]
    return {
        "total_deadlines": len(deadlines),
        "active_deadlines": len(active_deadlines),
        "domains_tracked": len(domain_map),
        "domain_names": sorted(domain_map.keys()),
    }
