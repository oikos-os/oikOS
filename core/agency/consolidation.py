"""Memory Consolidation Agent — promote session insights to vault knowledge.

Fresh build per Phase 7b Module 3 spec. Uses consolidate_memory Fabric pattern.
Proposals require Architect approval — no auto-writes to vault.
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Callable
from datetime import datetime, timezone, timedelta
from pathlib import Path

from core.interface.config import (
    CONSOLIDATION_CONFIDENCE_THRESHOLD,
    CONSOLIDATION_LOG_DIR,
    CONSOLIDATION_LOOKBACK_DAYS,
    CONSOLIDATION_MAX_FILES_PER_PASS,
    CONSOLIDATION_MODEL,
    CONSOLIDATION_PROPOSALS_LOG,
    CONSOLIDATION_SIMILARITY_DUPLICATE,
    CONSOLIDATION_SIMILARITY_FLAG,
    LANCEDB_DIR,
    LOGS_DIR,
    TABLE_NAME,
    VAULT_DIR,
)
from core.interface.models import PromotionProposal

log = logging.getLogger(__name__)


def _get_active_room_id() -> str:
    """Return the active Room ID, falling back to 'home'."""
    try:
        from core.rooms.manager import get_room_manager
        return get_room_manager().get_active_room().id
    except Exception:
        return "home"

PROCESSED_SESSIONS_FILE = CONSOLIDATION_LOG_DIR / "processed_sessions.json"

# Strategic reference files for divergence detection
_STRATEGIC_FILES = [
    VAULT_DIR / "identity" / "GOALS.md",
    VAULT_DIR / "identity" / "MISSION.md",
]


def _load_fabric_prompt() -> str:
    """Load the consolidate_memory Fabric pattern."""
    pattern_file = VAULT_DIR / "patterns" / "consolidate_memory" / "system.md"
    if pattern_file.exists():
        return pattern_file.read_text(encoding="utf-8")
    return ""


def _load_strategic_context() -> str:
    """Load GOALS.md and MISSION.md for strategic divergence checks."""
    parts = []
    for f in _STRATEGIC_FILES:
        if f.exists():
            parts.append(f"--- {f.name} ---\n{f.read_text(encoding='utf-8')}")
    return "\n\n".join(parts)


def _build_prompt(session_file: str, content: str) -> str:
    """Build the consolidation prompt with Fabric pattern + strategic context."""
    fabric = _load_fabric_prompt()
    strategic = _load_strategic_context()

    return f"""{fabric}

--- STRATEGIC REFERENCE (for divergence detection) ---
{strategic}

--- TASK ---
Analyze the following session log. Extract facts, decisions, milestones, and lessons that earn vault promotion per the rules above.

For each proposal, also check: does this decision CONTRADICT any goal or mission in the strategic reference above? If yes, set "strategic_divergence": true and explain the conflict in the evidence field.

If the session contains corrections, errors fixed, patterns that caused problems, or decisions with unexpected results, propose a LEARNINGS entry with:
- "insight_type": "lesson"
- "target_path": "vault/knowledge/LEARNINGS.md"
- Format the draft_content as: **L-NNN: [Short title]** [Description] ([Source], [Date])

SESSION LOG ({session_file}):
{content}

Respond with a JSON list. Each object:
- "insight_type": "fact" | "decision" | "preference" | "goal" | "lesson"
- "action": "CREATE" | "UPDATE" | "DELETE"
- "target_path": "vault/knowledge/<filename>.md" or "vault/identity/..."
- "target_section": "<section header>" or null
- "extracted_claim": "<the factual assertion>"
- "evidence": "<why it was extracted>"
- "confidence": <float 0.0-1.0>
- "strategic_divergence": true | false
- "conflict_with": null

If nothing earns promotion, return [].
Output raw JSON only. No markdown fences."""


# ── State Tracking ────────────────────────────────────────────────────
def _get_processed_sessions() -> set[str]:
    if not PROCESSED_SESSIONS_FILE.exists():
        return set()
    try:
        data = json.loads(PROCESSED_SESSIONS_FILE.read_text(encoding="utf-8"))
        return set(data.get("processed", []))
    except (json.JSONDecodeError, KeyError):
        return set()


def _mark_session_processed(filepath: str) -> None:
    PROCESSED_SESSIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
    processed = _get_processed_sessions()
    processed.add(filepath)
    PROCESSED_SESSIONS_FILE.write_text(
        json.dumps({"processed": sorted(processed)}), encoding="utf-8"
    )


# ── Proposal I/O ─────────────────────────────────────────────────────
def _save_proposal(proposal: PromotionProposal) -> None:
    CONSOLIDATION_PROPOSALS_LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(CONSOLIDATION_PROPOSALS_LOG, "a", encoding="utf-8") as f:
        f.write(proposal.model_dump_json() + "\n")


def _check_duplicate(extracted_claim: str) -> dict:
    """Semantic dedup against vault chunks in LanceDB."""
    try:
        import lancedb
        from core.memory.embedder import embed_single as embed_text

        db = lancedb.connect(str(LANCEDB_DIR))
        tables = db.list_tables()
        if TABLE_NAME not in tables:
            return {"is_duplicate": False, "status": "pending", "conflict_with": None}

        table = db.open_table(TABLE_NAME)
        vec = embed_text(extracted_claim)
        results = table.search(vec).limit(3).to_pandas()

        if results.empty:
            return {"is_duplicate": False, "status": "pending", "conflict_with": None}

        top_hit = results.iloc[0]
        similarity = 1.0 - float(top_hit["_distance"])

        if similarity > CONSOLIDATION_SIMILARITY_DUPLICATE:
            return {"is_duplicate": True, "status": "duplicate", "conflict_with": top_hit["chunk_id"]}
        if similarity > CONSOLIDATION_SIMILARITY_FLAG:
            return {"is_duplicate": False, "status": "pending", "conflict_with": top_hit["chunk_id"]}

    except Exception as e:
        log.warning("Duplicate check failed: %s", e)

    return {"is_duplicate": False, "status": "pending", "conflict_with": None}


# ── Core Engine ───────────────────────────────────────────────────────
def run_consolidation(
    on_progress: Callable[[str], None] | None = None,
) -> dict:
    """Run memory consolidation over unprocessed session logs.

    Args:
        on_progress: Optional callback for CLI progress updates.
    """
    from core.cognition.inference import generate_local

    try:
        from core.autonomic.events import emit_event
        emit_event("agent", "consolidation_start", {})
    except Exception:
        pass

    processed = _get_processed_sessions()

    # Lookback window: only scan sessions from last N days
    cutoff = datetime.now(timezone.utc) - timedelta(days=CONSOLIDATION_LOOKBACK_DAYS)
    session_files = [
        f for f in LOGS_DIR.glob("**/*.md")
        if f.stat().st_mtime >= cutoff.timestamp()
    ]
    session_files.sort(key=lambda x: x.stat().st_mtime)

    proposals_generated = 0
    files_processed = 0
    total_candidates = 0

    # Count unprocessed candidates for progress reporting
    candidates = []
    for sfile in session_files:
        rel_path = str(sfile.relative_to(LOGS_DIR.parent.parent))
        if rel_path not in processed:
            candidates.append((sfile, rel_path))
    total_candidates = min(len(candidates), CONSOLIDATION_MAX_FILES_PER_PASS)

    for i, (sfile, rel_path) in enumerate(candidates):
        if files_processed >= CONSOLIDATION_MAX_FILES_PER_PASS:
            break

        if on_progress:
            on_progress(f"Scanning session {i + 1}/{total_candidates}...")

        content = sfile.read_text(encoding="utf-8")
        if not content.strip():
            _mark_session_processed(rel_path)
            continue

        prompt = _build_prompt(rel_path, content[:8000])
        result = generate_local(prompt, model=CONSOLIDATION_MODEL)

        try:
            text = result.get("response", "").strip()
            if text.startswith("```json"):
                text = text[7:]
            if text.startswith("```"):
                text = text[3:]
            if text.endswith("```"):
                text = text[:-3]

            extracted = json.loads(text.strip())
            if not isinstance(extracted, list):
                extracted = []

            for ex in extracted:
                claim = ex.get("extracted_claim", "")
                if not claim:
                    continue

                confidence = float(ex.get("confidence", 0.0))
                if confidence < CONSOLIDATION_CONFIDENCE_THRESHOLD:
                    continue

                dup_info = _check_duplicate(claim)
                if dup_info["is_duplicate"]:
                    continue

                proposal = PromotionProposal(
                    proposal_id=str(uuid.uuid4())[:8],
                    source_session_ids=[rel_path],
                    insight_type=ex.get("insight_type", "fact"),
                    action=ex.get("action", "CREATE"),
                    summary=claim[:120],
                    draft_content=claim,
                    target_path=ex.get("target_path", ""),
                    target_section=ex.get("target_section"),
                    conflict_with=dup_info.get("conflict_with"),
                    strategic_divergence=bool(ex.get("strategic_divergence", False)),
                    heuristics_triggered=["consolidate_memory pattern"],
                    room_id=_get_active_room_id(),
                    status=dup_info["status"],
                    created_at=datetime.now(timezone.utc).isoformat(),
                )
                _save_proposal(proposal)
                proposals_generated += 1

        except json.JSONDecodeError as e:
            log.warning("Failed to parse consolidation JSON for %s: %s", rel_path, e)

        _mark_session_processed(rel_path)
        files_processed += 1

    result = {
        "files_processed": files_processed,
        "proposals_generated": proposals_generated,
    }

    try:
        from core.autonomic.events import emit_event
        emit_event("agent", "consolidation_complete", result)
    except Exception:
        pass

    return result


# ── Proposal Access ──────────────────────────────────────────────────
def load_pending_proposals(room_id: str | None = None) -> list[PromotionProposal]:
    """Load proposals awaiting Architect review, optionally filtered by Room."""
    if not CONSOLIDATION_PROPOSALS_LOG.exists():
        return []

    if room_id is None:
        room_id = _get_active_room_id()

    proposals = []
    for line in CONSOLIDATION_PROPOSALS_LOG.read_text(encoding="utf-8").strip().split("\n"):
        if not line.strip():
            continue
        try:
            prop = PromotionProposal.model_validate_json(line)
            if prop.status == "pending" and prop.room_id == room_id:
                proposals.append(prop)
        except Exception:
            continue

    return proposals


def mark_proposal_status(proposal_id: str, status: str, apply: bool = False) -> None:
    """Update proposal status. If apply=True and status is approved, write to vault."""
    if not CONSOLIDATION_PROPOSALS_LOG.exists():
        return

    lines = CONSOLIDATION_PROPOSALS_LOG.read_text(encoding="utf-8").strip().split("\n")
    proposals = []
    updated = False

    for line in lines:
        if not line.strip():
            continue
        try:
            prop = PromotionProposal.model_validate_json(line)
            if prop.proposal_id == proposal_id:
                prop.status = status
                if apply:
                    _apply_proposal(prop)
                updated = True
            proposals.append(prop)
        except Exception:
            continue

    if updated:
        CONSOLIDATION_PROPOSALS_LOG.write_text(
            "\n".join(p.model_dump_json() for p in proposals) + "\n",
            encoding="utf-8",
        )


def _apply_proposal(proposal: PromotionProposal) -> None:
    """Write approved proposal content to the vault."""
    target_path_str = proposal.target_path
    if target_path_str.startswith("vault/"):
        target_path_str = target_path_str[6:]

    # Reject path traversal attempts
    if ".." in target_path_str or "\x00" in target_path_str:
        raise ValueError(f"Invalid target_path: contains traversal characters")
    target_file = VAULT_DIR / target_path_str
    if not target_file.resolve().is_relative_to(VAULT_DIR.resolve()):
        raise ValueError(f"Invalid target_path: escapes vault boundary")
    target_file.parent.mkdir(parents=True, exist_ok=True)

    claim = proposal.draft_content
    section = proposal.target_section
    content_to_add = f"\n- {claim}\n"

    if target_file.exists():
        content = target_file.read_text(encoding="utf-8")
        if section and section in content:
            parts = content.split(section)
            new_content = parts[0] + section + content_to_add + parts[1]
            target_file.write_text(new_content, encoding="utf-8")
        else:
            if section:
                content_to_add = f"\n## {section}\n{content_to_add}"
            with open(target_file, "a", encoding="utf-8") as f:
                f.write(content_to_add)
    else:
        if section:
            new_content = f"# {target_file.stem.upper()}\n\n## {section}\n{content_to_add}"
        else:
            new_content = f"# {target_file.stem.upper()}\n{content_to_add}"
        target_file.write_text(new_content, encoding="utf-8")
