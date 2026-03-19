"""Pattern scanner — cross-domain connection discovery via Optimist/Pessimist passes."""

from __future__ import annotations

import hashlib
import json
import logging
import random
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from core.interface.config import (
    SCANNER_BLIP_EXPIRY_DAYS,
    SCANNER_BLIP_LOG,
    SCANNER_MIN_DOMAINS,
    SCANNER_MIN_FILE_SIZE,
    SCANNER_MIN_FILES,
    SCANNER_PAIRS_PER_SCAN,
    SCANNER_RESONANCE_THRESHOLD,
    VAULT_DIR,
)
from core.interface.models import Blip

log = logging.getLogger(__name__)


# ── Activation gate ──────────────────────────────────────────────────


def check_activation_gate(vault_dir: Path | None = None) -> dict:
    """Check if vault has enough content for scanning.

    Returns {"active": bool, "reason": str, "stats": {...}}.
    """
    vdir = vault_dir or VAULT_DIR
    files_by_domain: dict[str, list[Path]] = {}

    for subdir in vdir.iterdir():
        if not subdir.is_dir():
            continue
        domain = subdir.name
        substantive = [
            f for f in subdir.rglob("*.md")
            if f.stat().st_size >= SCANNER_MIN_FILE_SIZE
        ]
        if substantive:
            files_by_domain[domain] = substantive

    total_files = sum(len(v) for v in files_by_domain.values())
    domain_count = len(files_by_domain)

    if total_files < SCANNER_MIN_FILES:
        return {
            "active": False,
            "reason": f"Insufficient files: {total_files}/{SCANNER_MIN_FILES}",
            "stats": {"files": total_files, "domains": domain_count},
        }
    if domain_count < SCANNER_MIN_DOMAINS:
        return {
            "active": False,
            "reason": f"Insufficient domains: {domain_count}/{SCANNER_MIN_DOMAINS}",
            "stats": {"files": total_files, "domains": domain_count},
        }

    return {
        "active": True,
        "reason": "Gate cleared",
        "stats": {"files": total_files, "domains": domain_count},
    }


# ── Pair selection ───────────────────────────────────────────────────


def _select_cross_domain_pairs(limit: int = SCANNER_PAIRS_PER_SCAN) -> list[tuple[dict, dict]]:
    """Select random chunk pairs from different tiers (different source files).

    Queries LanceDB for all chunks, groups by tier, picks cross-tier pairs.
    Deduplication: rejects pairs from the same source file.
    """
    try:
        from core.interface.config import LANCEDB_DIR, TABLE_NAME
        import lancedb

        db = lancedb.connect(str(LANCEDB_DIR))
        resp = db.list_tables()
        table_names = resp.tables if hasattr(resp, "tables") else [str(t) for t in resp]
        if TABLE_NAME not in table_names:
            return []

        table = db.open_table(TABLE_NAME)
        df = table.to_pandas()

        if df.empty:
            return []

        # Group chunks by tier
        tiers = df["tier"].unique().tolist()
        if len(tiers) < 2:
            return []

        chunks_by_tier: dict[str, list[dict]] = {}
        for tier in tiers:
            tier_rows = df[df["tier"] == tier]
            chunks_by_tier[tier] = [
                {
                    "chunk_id": row["chunk_id"],
                    "source_path": row["source_path"],
                    "tier": row["tier"],
                    "content_preview": row["content"][:500],
                }
                for _, row in tier_rows.iterrows()
            ]

        # Select cross-tier pairs (different tiers, different source files)
        pairs = []
        seen_file_pairs: set[tuple[str, str]] = set()
        attempts = 0
        max_attempts = limit * 10

        while len(pairs) < limit and attempts < max_attempts:
            attempts += 1
            tier_a, tier_b = random.sample(tiers, 2)
            chunk_a = random.choice(chunks_by_tier[tier_a])
            chunk_b = random.choice(chunks_by_tier[tier_b])

            # Reject same source file
            if chunk_a["source_path"] == chunk_b["source_path"]:
                continue

            # Reject duplicate file pairs (order-independent)
            file_key = tuple(sorted([chunk_a["source_path"], chunk_b["source_path"]]))
            if file_key in seen_file_pairs:
                continue
            seen_file_pairs.add(file_key)
            pairs.append((chunk_a, chunk_b))

        return pairs

    except Exception as e:
        log.warning("Pair selection failed: %s", e)
        return []


# ── Optimist pass (local) ───────────────────────────────────────────

OPTIMIST_PROMPT = """You are analyzing two pieces of knowledge from different domains.
Find non-obvious connections, tensions, or opportunities between them.

SCORING CALIBRATION:
- 0-20: No meaningful connection. Shared vocabulary does not count.
- 21-50: Superficial or trivially obvious link (e.g. "both mention the Architect").
- 51-75: Interesting parallel, but not actionable.
- 76-100: Genuinely surprising insight that could change a decision or strategy.
Only score above 50 if the connection would surprise someone who knows both domains well.

CHUNK A ({tier_a}):
{content_a}

CHUNK B ({tier_b}):
{content_b}

Respond with EXACTLY this format:
SCORE: <number 0-100>
OBSERVATION: <one sentence describing the connection>"""


def _parse_optimist_response(text: str) -> dict:
    """Extract SCORE and OBSERVATION from optimist response."""
    score = 0.0
    observation = ""

    score_match = re.search(r"SCORE:\s*(\d+(?:\.\d+)?)", text)
    if score_match:
        score = min(100.0, max(0.0, float(score_match.group(1))))

    obs_match = re.search(r"OBSERVATION:\s*(.+)", text, re.DOTALL)
    if obs_match:
        observation = obs_match.group(1).strip().split("\n")[0]

    return {"score": score, "observation": observation}


def _optimist_pass(chunk_a: dict, chunk_b: dict) -> dict:
    """Local inference pass — find connections between two chunks."""
    from core.cognition.inference import generate_local

    prompt = OPTIMIST_PROMPT.format(
        tier_a=chunk_a["tier"],
        content_a=chunk_a["content_preview"][:500],
        tier_b=chunk_b["tier"],
        content_b=chunk_b["content_preview"][:500],
    )

    result = generate_local(prompt)
    if "error" in result:
        return {"score": 0.0, "observation": f"[inference error: {result['error']}]"}

    return _parse_optimist_response(result["response"])


# ── Pessimist pass (cloud) ───────────────────────────────────────────

PESSIMIST_PROMPT = """You are a critical analyst. An AI found a proposed connection between two knowledge domains.

CHUNK A ({tier_a}):
{content_a}

CHUNK B ({tier_b}):
{content_b}

PROPOSED CONNECTION (score {optimist_score}/100):
{observation}

Your job: attempt to debunk this connection. How likely is it to be coincidental, shallow, or already obvious?

Respond with EXACTLY this format:
KILL_PROBABILITY: <number 0-100>
REASONING: <one sentence>"""


def _parse_pessimist_response(text: str) -> dict:
    """Extract KILL_PROBABILITY and REASONING from pessimist response."""
    kill_prob = 50.0
    reasoning = ""

    kp_match = re.search(r"KILL_PROBABILITY:\s*(\d+(?:\.\d+)?)", text)
    if kp_match:
        kill_prob = min(100.0, max(0.0, float(kp_match.group(1))))

    reason_match = re.search(r"REASONING:\s*(.+)", text, re.DOTALL)
    if reason_match:
        reasoning = reason_match.group(1).strip().split("\n")[0]

    return {"kill_probability": kill_prob, "reasoning": reasoning}


def _pessimist_pass(chunk_a: dict, chunk_b: dict, observation: str, optimist_score: float) -> dict:
    """Cloud inference pass — adversarial debunk attempt."""
    from core.cognition.cloud import send_to_cloud
    from core.safety.credits import check_hard_ceiling

    if check_hard_ceiling():
        log.warning("Hard ceiling — skipping pessimist pass")
        return {"kill_probability": None, "reasoning": "budget_skip"}

    prompt = PESSIMIST_PROMPT.format(
        tier_a=chunk_a["tier"],
        content_a=chunk_a["content_preview"][:500],
        tier_b=chunk_b["tier"],
        content_b=chunk_b["content_preview"][:500],
        optimist_score=optimist_score,
        observation=observation,
    )

    try:
        resp = send_to_cloud(prompt, context="", system="You are a critical analyst.")
        return _parse_pessimist_response(resp.text)
    except Exception as e:
        log.warning("Pessimist pass failed: %s", e)
        return {"kill_probability": None, "reasoning": f"error: {e}"}


# ── Resonance ────────────────────────────────────────────────────────


def compute_resonance(optimist_score: float, kill_probability: float | None) -> float | None:
    """Resonance = optimist_score * (1 - kill_probability / 100). None if pessimist skipped."""
    if kill_probability is None:
        return None
    return optimist_score * (1 - kill_probability / 100)


# ── Blip management ─────────────────────────────────────────────────


def _blip_id(chunk_a_id: str, chunk_b_id: str) -> str:
    """Deterministic blip ID from sorted chunk pair."""
    pair = "".join(sorted([chunk_a_id, chunk_b_id]))
    return hashlib.sha256(pair.encode()).hexdigest()[:16]


def _save_blip(blip: Blip) -> None:
    """Append blip to JSONL log."""
    SCANNER_BLIP_LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(SCANNER_BLIP_LOG, "a", encoding="utf-8") as f:
        f.write(blip.model_dump_json() + "\n")


def _load_all_blips() -> list[Blip]:
    """Load all blips from JSONL."""
    if not SCANNER_BLIP_LOG.exists():
        return []

    blips = []
    for line in SCANNER_BLIP_LOG.read_text(encoding="utf-8").strip().split("\n"):
        if line.strip():
            try:
                blips.append(Blip.model_validate_json(line))
            except Exception:
                continue
    return blips


def load_undelivered_blips() -> list[Blip]:
    """Load blips that are undelivered and not expired."""
    now = datetime.now(timezone.utc)
    blips = _load_all_blips()
    return [
        b for b in blips
        if not b.delivered
        and datetime.fromisoformat(b.expires_at) > now
    ]


def mark_blips_delivered(blip_ids: list[str]) -> None:
    """Rewrite JSONL with delivered=True for matching IDs."""
    if not SCANNER_BLIP_LOG.exists():
        return

    blips = _load_all_blips()
    ids_set = set(blip_ids)
    updated = []
    for b in blips:
        if b.blip_id in ids_set:
            b.delivered = True
        updated.append(b)

    SCANNER_BLIP_LOG.write_text(
        "\n".join(b.model_dump_json() for b in updated) + "\n",
        encoding="utf-8",
    )


# ── Main entry ───────────────────────────────────────────────────────


def run_scan(vault_dir: Path | None = None) -> dict:
    """Run a full scan cycle: gate → pairs → optimist → pessimist → resonance → save.

    Returns {"blips": [...], "pairs_evaluated": int, "pairs_above_threshold": int}.
    """
    gate = check_activation_gate(vault_dir)
    if not gate["active"]:
        return {
            "blips": [],
            "pairs_evaluated": 0,
            "pairs_above_threshold": 0,
            "gate_reason": gate["reason"],
        }

    pairs = _select_cross_domain_pairs(limit=SCANNER_PAIRS_PER_SCAN)
    if not pairs:
        return {"blips": [], "pairs_evaluated": 0, "pairs_above_threshold": 0}

    now = datetime.now(timezone.utc)
    expiry = now + timedelta(days=SCANNER_BLIP_EXPIRY_DAYS)
    blips: list[Blip] = []

    for chunk_a, chunk_b in pairs:
        # Optimist pass
        opt = _optimist_pass(chunk_a, chunk_b)

        kill_prob = None
        reasoning = ""

        # Pessimist pass (only if optimist score > 50)
        if opt["score"] > 50:
            pess = _pessimist_pass(chunk_a, chunk_b, opt["observation"], opt["score"])
            kill_prob = pess["kill_probability"]
            reasoning = pess.get("reasoning", "")

        # Resonance
        resonance = compute_resonance(opt["score"], kill_prob)

        # Filter: persist only if resonance > threshold OR pessimist was skipped (unvalidated)
        if resonance is not None and resonance < SCANNER_RESONANCE_THRESHOLD:
            continue
        if resonance is None and opt["score"] <= 50:
            continue  # Low optimist, no pessimist → discard

        blip = Blip(
            blip_id=_blip_id(chunk_a["chunk_id"], chunk_b["chunk_id"]),
            generated_at=now.isoformat(),
            chunk_a=chunk_a,
            chunk_b=chunk_b,
            optimist_score=opt["score"],
            pessimist_kill_probability=kill_prob,
            resonance=resonance,
            observation=opt["observation"],
            delivered=False,
            expires_at=expiry.isoformat(),
        )
        _save_blip(blip)
        blips.append(blip)

    return {
        "blips": blips,
        "pairs_evaluated": len(pairs),
        "pairs_above_threshold": len(blips),
    }
