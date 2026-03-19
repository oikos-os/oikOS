"""Novel assertion detector — checks incoming query claims against vault canon."""

from __future__ import annotations

import json
import logging
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import NamedTuple

from core.interface.config import ASSERTION_CLASSIFIER_MODEL, ASSERTION_LOG_DIR, ASSERTION_MAX_TOKENS

log = logging.getLogger(__name__)


class AssertionResult(NamedTuple):
    """Result of assertion detection pipeline."""
    contains_assertion: bool
    assertion_type: str        # "location"|"relationship"|"employment"|"project_status"|"identity"|"none"
    extracted_claim: str | None
    vault_chunks: list[dict]   # conflicting CORE chunks (empty = no conflict or no assertion)


# ---------------------------------------------------------------------------
# Regex pre-filter (R-02: 100% recall with negation pattern)
# ---------------------------------------------------------------------------

_ASSERTION_PATTERNS = [
    r'(?i)\bI (moved?|relocated|left|quit|got (fired|hired|a job)|started (working|dating)|stopped|shut down|am now|go by|ended)\b',
    r'(?i)\bmy (girlfriend|boyfriend|wife|husband|partner|ex|fiancee?)\b',
    r'(?i)\b(call me|my name is|everyone calls me|I go by|I\'m going by)\b',
    r'(?i)\bI (live|moved?) (in|to|at)\b',
    r'(?i)\bI (am|was) (now |recently |currently )?(at|with|in|working|dating|living)\b',
    r'(?i)\bI (cancelled|canceled|abandoned|closed|ended|finished)\b',
    r'(?i)\bI (did not|didn\'t) (move|quit|leave|go|work|date|live)\b',
]

# ---------------------------------------------------------------------------
# Classifier prompt (R-02 v2 — 95% accuracy on qwen2.5:7b)
# ---------------------------------------------------------------------------

_CLASSIFIER_PROMPT = """You are an assertion detector. Given a user query, determine if it contains a FIRST-PERSON DECLARATIVE assertion about the user's own real-world state.

Rules:
- MUST be first-person (about the speaker, not third parties)
- MUST be declarative — not hedged ("thinking about", "considering", "maybe", "might"), not a question
- Assertions include: location change, relationships, employment change, project status, identity

Respond with JSON only:
{{
  "contains_assertion": true/false,
  "assertion_type": "location|relationship|employment|project_status|identity|none",
  "extracted_claim": "the specific first-person claim, or null"
}}

Query: {query}"""


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _regex_prefilter(query: str) -> bool:
    """Return True if any assertion pattern matches. Microseconds."""
    return any(re.search(pat, query) for pat in _ASSERTION_PATTERNS)


def _classify_assertion(query: str) -> dict | None:
    """
    Call qwen2.5:7b to classify assertion. Returns raw dict or None on failure.
    Uses direct Ollama client to allow model override (not INFERENCE_MODEL).
    """
    from core.interface.config import INFERENCE_TIMEOUT_SECONDS

    try:
        import ollama as _ollama
        client = _ollama.Client(timeout=INFERENCE_TIMEOUT_SECONDS)
        resp = client.generate(
            model=ASSERTION_CLASSIFIER_MODEL,
            prompt=_CLASSIFIER_PROMPT.format(query=query),
            options={"num_predict": ASSERTION_MAX_TOKENS, "temperature": 0.0},
        )
        raw_text = resp.get("response", "").strip()
        # Strip markdown code fences if present
        raw_text = re.sub(r"^```(?:json)?\s*", "", raw_text, flags=re.MULTILINE)
        raw_text = re.sub(r"\s*```$", "", raw_text, flags=re.MULTILINE)
        return json.loads(raw_text)
    except Exception as e:
        log.warning("[ASSERTION] classifier failed: %s", e)
        return None


def _vault_lookup(claim: str) -> list[dict]:
    """Search CORE tier for chunks that may conflict with the claim."""
    try:
        from core.memory.search import hybrid_search
        from core.interface.models import MemoryTier

        results = hybrid_search(claim, limit=5, tier_filter=MemoryTier.CORE)
        return [{"source_path": r.source_path, "content": r.content} for r in results]
    except Exception as e:
        log.warning("[ASSERTION] vault lookup failed: %s", e)
        return []


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def check_assertion(query: str) -> AssertionResult:
    """
    Full assertion detection pipeline.

    1. Regex pre-filter (~75-80% of queries exit here)
    2. LLM classifier (qwen2.5:7b, p50=0.47s warm)
    3. Vault CORE lookup for conflicting chunks

    Returns AssertionResult — never raises.
    """
    _clean = AssertionResult(False, "none", None, [])

    # Step 1: regex pre-filter
    if not _regex_prefilter(query):
        return _clean

    # Step 2: LLM classifier
    classified = _classify_assertion(query)
    if classified is None:
        return _clean

    if not classified.get("contains_assertion", False):
        return _clean

    assertion_type = classified.get("assertion_type", "none") or "none"
    extracted_claim = classified.get("extracted_claim") or None

    # Step 3: vault lookup (only if we have a concrete claim)
    vault_chunks: list[dict] = []
    if extracted_claim:
        vault_chunks = _vault_lookup(extracted_claim)

    return AssertionResult(
        contains_assertion=True,
        assertion_type=assertion_type,
        extracted_claim=extracted_claim,
        vault_chunks=vault_chunks,
    )


def log_assertion(
    session_id: str,
    result: AssertionResult,
    vault_result: str,
    nli: object | None,
) -> str:
    """
    Write assertion to JSONL log. Returns entry ID (uuid4[:8]).

    vault_result: "new" | "conflict" | "no_lookup"
    """
    ASSERTION_LOG_DIR.mkdir(parents=True, exist_ok=True)

    entry_id = uuid.uuid4().hex[:8]
    now = datetime.now(timezone.utc)
    log_file = ASSERTION_LOG_DIR / f"{now.strftime('%Y-%m-%d')}.jsonl"

    nli_contradiction = False
    if nli is not None:
        try:
            nli_contradiction = bool(nli.has_contradiction)
        except AttributeError:
            pass

    entry = {
        "id": entry_id,
        "timestamp": now.isoformat(),
        "session_id": session_id,
        "assertion_type": result.assertion_type,
        "extracted_claim": result.extracted_claim,
        "vault_result": vault_result,
        "nli_contradiction": nli_contradiction,
        "delivered": False,
    }

    with open(log_file, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry) + "\n")

    log.debug("[ASSERTION] logged id=%s type=%s vault_result=%s", entry_id, result.assertion_type, vault_result)
    return entry_id


def load_undelivered_assertions() -> list[dict]:
    """Load undelivered assertion entries from today's and yesterday's JSONL files."""
    now = datetime.now(timezone.utc)
    dates = [
        now.strftime("%Y-%m-%d"),
        (now - timedelta(days=1)).strftime("%Y-%m-%d"),
    ]

    undelivered: list[dict] = []
    for date_str in dates:
        log_file = ASSERTION_LOG_DIR / f"{date_str}.jsonl"
        if not log_file.exists():
            continue
        try:
            with open(log_file, encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    entry = json.loads(line)
                    if not entry.get("delivered", True):
                        undelivered.append(entry)
        except Exception as e:
            log.warning("[ASSERTION] failed to load %s: %s", log_file, e)

    return undelivered


def mark_assertions_delivered(ids: list[str]) -> None:
    """Rewrite JSONL files setting delivered=True for matching IDs."""
    if not ids:
        return

    id_set = set(ids)
    now = datetime.now(timezone.utc)
    dates = [
        now.strftime("%Y-%m-%d"),
        (now - timedelta(days=1)).strftime("%Y-%m-%d"),
    ]

    for date_str in dates:
        log_file = ASSERTION_LOG_DIR / f"{date_str}.jsonl"
        if not log_file.exists():
            continue
        try:
            entries: list[dict] = []
            with open(log_file, encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    entry = json.loads(line)
                    if entry.get("id") in id_set:
                        entry["delivered"] = True
                    entries.append(entry)

            with open(log_file, "w", encoding="utf-8") as fh:
                for entry in entries:
                    fh.write(json.dumps(entry) + "\n")
        except Exception as e:
            log.warning("[ASSERTION] failed to rewrite %s: %s", log_file, e)
