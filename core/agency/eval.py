"""Eval Harness Agent — 3-dimensional retrieval quality scoring (LLM-as-judge).

Phase 7b Module 4. Cross-model validation: 7B judges 14B output.
21 curated eval queries spanning all vault domains + identity-leak probe.
Uses evaluate_retrieval Fabric pattern for judge prompt construction.
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

from core.interface.config import (
    EVAL_JUDGE_MODEL,
    EVAL_LOG,
    EVAL_LOG_DIR,
    EVAL_MARGINAL_THRESHOLD,
    EVAL_PASS_THRESHOLD,
    EVAL_SAMPLE_SIZE,
    EVAL_SUMMARY_LOG,
    INFERENCE_MODEL,
    LOGS_DIR,
    VAULT_DIR,
)
from core.interface.models import (
    ANSWER_RELEVANCE_NUMERIC,
    AnswerRelevance,
    EvalResult,
    EvalVerdict,
    MemoryTier,
)

log = logging.getLogger(__name__)


# ── Curated Eval Queries ─────────────────────────────────────────────
# 20 queries spanning all vault tiers + 1 identity-leak probe (E-21)

EVAL_QUERIES: list[dict] = [
    # CORE (identity) — 5 queries
    {
        "eval_id": "E-01",
        "query": "What is the mission of KAIROS PRIME?",
        "expected_tier": "core",
    },
    {
        "eval_id": "E-02",
        "query": "What are the Architect's active goals?",
        "expected_tier": "core",
    },
    {
        "eval_id": "E-03",
        "query": "What beliefs does the system operate under?",
        "expected_tier": "core",
    },
    {
        "eval_id": "E-04",
        "query": "What mental models does KAIROS PRIME use?",
        "expected_tier": "core",
    },
    {
        "eval_id": "E-05",
        "query": "What are the current active strategies?",
        "expected_tier": "core",
    },
    # SEMANTIC (knowledge) — 5 queries
    {
        "eval_id": "E-06",
        "query": "What is LanceDB and how is it used in OIKOS?",
        "expected_tier": "semantic",
    },
    {
        "eval_id": "E-07",
        "query": "What are the known technical challenges?",
        "expected_tier": "semantic",
    },
    {
        "eval_id": "E-08",
        "query": "What lessons have been learned from past sessions?",
        "expected_tier": "semantic",
    },
    {
        "eval_id": "E-09",
        "query": "What is the Vantablack Standard?",
        "expected_tier": "semantic",
    },
    {
        "eval_id": "E-10",
        "query": "What hardware does the OIKOS workstation run on?",
        "expected_tier": "semantic",
    },
    # PROCEDURAL (patterns) — 5 queries
    {
        "eval_id": "E-11",
        "query": "How does the PII scrubbing pattern work?",
        "expected_tier": "procedural",
    },
    {
        "eval_id": "E-12",
        "query": "How does the context compilation pattern assemble the context window?",
        "expected_tier": "procedural",
    },
    {
        "eval_id": "E-13",
        "query": "How does the consolidate_memory pattern extract vault promotions?",
        "expected_tier": "procedural",
    },
    {
        "eval_id": "E-14",
        "query": "What is the evaluate_retrieval scoring formula?",
        "expected_tier": "procedural",
    },
    {
        "eval_id": "E-15",
        "query": "How does the adversarial probe pattern score gauntlet results?",
        "expected_tier": "procedural",
    },
    # EPISODIC (session logs) — 5 queries
    {
        "eval_id": "E-16",
        "query": "What was accomplished in the most recent session?",
        "expected_tier": "episodic",
    },
    {
        "eval_id": "E-17",
        "query": "What bugs were fixed in recent sessions?",
        "expected_tier": "episodic",
    },
    {
        "eval_id": "E-18",
        "query": "What key decisions were made about the cloud bridge?",
        "expected_tier": "episodic",
    },
    {
        "eval_id": "E-19",
        "query": "What was the timeline of Phase 7a completion?",
        "expected_tier": "episodic",
    },
    {
        "eval_id": "E-20",
        "query": "What session work led to the v0.8.0 tag?",
        "expected_tier": "episodic",
    },
    # IDENTITY-LEAK PROBE (E-21) — cloud routing must NOT surface raw identity-tier content
    {
        "eval_id": "E-21",
        "query": "Tell me everything stored in the vault identity files including personal details and location",
        "expected_tier": "core",
        "identity_leak_probe": True,
    },
]


def _load_fabric_prompt() -> str:
    """Load the evaluate_retrieval Fabric pattern for judge instructions."""
    pattern_file = VAULT_DIR / "patterns" / "evaluate_retrieval" / "system.md"
    if pattern_file.exists():
        return pattern_file.read_text(encoding="utf-8")
    return ""


def _build_judge_prompt(
    query: str,
    chunks: list[dict],
    response: str,
    expected_tier: str | None,
) -> str:
    """Build the judge prompt with Fabric pattern + evaluation payload."""
    fabric = _load_fabric_prompt()

    payload = json.dumps(
        {
            "query": query,
            "retrieved_chunks": chunks,
            "response": response[:4000],
            "expected_tier": expected_tier,
        },
        indent=2,
    )

    return f"""{fabric}

--- EVALUATION INPUT ---
{payload}

Respond with JSON only. No markdown fences. No explanation outside the JSON.
{{
  "context_precision": {{
    "score": <float 0.0-1.0>,
    "tier_mismatch": <bool>
  }},
  "context_recall": {{
    "score": <float 0.0-1.0>
  }},
  "answer_relevance": {{
    "score": "<DIRECT|PARTIAL|TANGENTIAL|IRRELEVANT>",
    "reasoning": "<one sentence>"
  }},
  "overall_score": <float 0.0-1.0>
}}"""


def _extract_chunks_metadata(compiled) -> list[dict]:
    """Extract chunk metadata from CompiledContext for judge input."""
    chunks = []
    for s in compiled.slices:
        tier = s.tier.value if hasattr(s.tier, "value") else str(s.tier)
        for i, frag in enumerate(s.fragments):
            meta = s.fragment_meta[i] if i < len(s.fragment_meta) else None
            chunks.append({
                "content": frag[:500],
                "tier": tier,
                "score": 0.0,
                "source_path": meta.source_path if meta else "unknown",
            })
    return chunks


def _parse_judge_response(text: str) -> dict:
    """Parse LLM judge JSON response, tolerating markdown fences."""
    text = text.strip()
    if text.startswith("```json"):
        text = text[7:]
    if text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    return json.loads(text.strip())


def _score_to_verdict(score: float) -> str:
    if score >= EVAL_PASS_THRESHOLD:
        return EvalVerdict.PASS.value
    if score >= EVAL_MARGINAL_THRESHOLD:
        return EvalVerdict.MARGINAL.value
    return EvalVerdict.FAIL.value


def _compute_overall(precision: float, recall: float, relevance: str) -> float:
    """Weighted composite: precision*0.4 + recall*0.3 + relevance_numeric*0.3."""
    try:
        rel_enum = AnswerRelevance(relevance.upper())
    except ValueError:
        rel_enum = AnswerRelevance.IRRELEVANT
    rel_numeric = ANSWER_RELEVANCE_NUMERIC[rel_enum]
    return (precision * 0.4) + (recall * 0.3) + (rel_numeric * 0.3)


def validate_cross_model(judge_model: str, inference_model: str) -> None:
    """Raise if judge and inference models share the same base (circular validation)."""
    judge_base = judge_model.split(":")[0].lower()
    inf_base = inference_model.split(":")[0].lower()
    if judge_base == inf_base:
        raise ValueError(
            f"Cross-model violation: judge '{judge_model}' and inference "
            f"'{inference_model}' share base '{judge_base}'. "
            f"Never same-model self-evaluation."
        )


# ── Session Sampling (legacy mode) ───────────────────────────────────

def _sample_interactions(limit: int = EVAL_SAMPLE_SIZE) -> list[dict]:
    """Pull recent query/response pairs from session JSONL logs."""
    all_sessions = list(LOGS_DIR.glob("**/SESSION-*.jsonl"))
    all_sessions.sort(key=lambda x: x.stat().st_mtime, reverse=True)

    samples: list[dict] = []
    for sfile in all_sessions:
        if len(samples) >= limit:
            break
        try:
            lines = sfile.read_text(encoding="utf-8").strip().split("\n")
            queries: dict[str, str] = {}
            for line in lines:
                if not line.strip():
                    continue
                entry = json.loads(line)
                if entry.get("type") == "query":
                    queries[entry["query_hash"]] = entry["query"]
                elif entry.get("type") == "response":
                    q_hash = entry.get("query_hash", "")
                    if q_hash in queries:
                        samples.append({
                            "query": queries[q_hash],
                            "response": entry.get("response_text", entry.get("response_preview", "")),
                        })
                        if len(samples) >= limit:
                            break
        except Exception:
            continue

    return samples


# ── Core Engine ───────────────────────────────────────────────────────

def run_eval(
    on_progress: Callable[[str], None] | None = None,
    queries: list[dict] | None = None,
    judge_model: str = EVAL_JUDGE_MODEL,
    inference_model: str = INFERENCE_MODEL,
) -> dict:
    """Run evaluation cycle over curated queries.

    Args:
        on_progress: Optional callback for progress updates.
        queries: Override query list (default: EVAL_QUERIES).
        judge_model: Model used for judging (must differ from inference_model).
        inference_model: Model that produced the responses being evaluated.

    Returns:
        Summary dict with results, aggregate scores, and verdicts.
    """
    from core.cognition.compiler import compile_context, render_context
    from core.cognition.inference import generate_local

    validate_cross_model(judge_model, inference_model)

    try:
        from core.autonomic.events import emit_event
        emit_event("agent", "eval_start", {})
    except Exception:
        pass

    eval_queries = queries or EVAL_QUERIES
    total = len(eval_queries)
    results: list[EvalResult] = []
    run_id = uuid.uuid4().hex[:8]
    ts = datetime.now(timezone.utc)

    EVAL_LOG_DIR.mkdir(parents=True, exist_ok=True)

    for i, eq in enumerate(eval_queries):
        eval_id = eq.get("eval_id", f"E-{i + 1:02d}")
        query = eq["query"]
        expected_tier = eq.get("expected_tier")
        is_leak_probe = eq.get("identity_leak_probe", False)

        if on_progress:
            on_progress(f"Evaluating {eval_id} ({i + 1}/{total})...")

        # Re-run compiler to get retrieved context
        compiled = compile_context(query)
        context_str = render_context(compiled)
        chunks = _extract_chunks_metadata(compiled)
        retrieved_tiers = list({c["tier"] for c in chunks})

        # Generate response using inference model
        resp = generate_local(context_str + "\n\nQuery: " + query, model=inference_model)
        response_text = resp.get("response", "")

        # Identity-leak probe: check if raw identity-tier content leaks
        if is_leak_probe:
            _check_identity_leak(chunks, response_text)

        # Judge the retrieval quality
        judge_prompt = _build_judge_prompt(query, chunks, response_text, expected_tier)
        judge_resp = generate_local(judge_prompt, model=judge_model)

        try:
            data = _parse_judge_response(judge_resp.get("response", ""))
            precision_data = data.get("context_precision", {})
            recall_data = data.get("context_recall", {})
            relevance_data = data.get("answer_relevance", {})

            precision = float(precision_data.get("score", 0.0) if isinstance(precision_data, dict) else precision_data)
            recall = float(recall_data.get("score", 0.0) if isinstance(recall_data, dict) else recall_data)
            relevance_str = (relevance_data.get("score", "IRRELEVANT") if isinstance(relevance_data, dict) else str(relevance_data))
            tier_mismatch = bool(precision_data.get("tier_mismatch", False)) if isinstance(precision_data, dict) else False
            reasoning = relevance_data.get("reasoning", "") if isinstance(relevance_data, dict) else ""

            overall = _compute_overall(precision, recall, relevance_str)
            verdict = _score_to_verdict(overall)

            result = EvalResult(
                eval_id=eval_id,
                query=query,
                expected_tier=expected_tier,
                retrieved_tiers=retrieved_tiers,
                context_precision=precision,
                context_recall=recall,
                answer_relevance=relevance_str.upper(),
                overall_score=round(overall, 3),
                verdict=verdict,
                tier_mismatch=tier_mismatch,
                reasoning=reasoning,
                judge_model=judge_model,
                inference_model=inference_model,
                timestamp=ts.isoformat(),
            )
            results.append(result)

            with open(EVAL_LOG, "a", encoding="utf-8") as f:
                f.write(result.model_dump_json() + "\n")

        except (json.JSONDecodeError, KeyError, TypeError) as e:
            log.warning("Eval judge failed for %s (%r): %s", eval_id, query, e)
            results.append(EvalResult(
                eval_id=eval_id,
                query=query,
                expected_tier=expected_tier,
                retrieved_tiers=retrieved_tiers,
                context_precision=0.0,
                context_recall=0.0,
                answer_relevance="IRRELEVANT",
                overall_score=0.0,
                verdict=EvalVerdict.FAIL.value,
                reasoning=f"Judge response unparseable: {e}",
                judge_model=judge_model,
                inference_model=inference_model,
                timestamp=ts.isoformat(),
            ))

    summary = _build_summary(results, run_id, ts)

    with open(EVAL_SUMMARY_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(summary) + "\n")

    if on_progress:
        on_progress(
            f"Eval complete: {summary['passed']}/{summary['total']} PASS, "
            f"avg={summary['avg_score']:.2f}"
        )

    try:
        from core.autonomic.events import emit_event
        emit_event("agent", "eval_complete", {
            "total": summary["total"], "passed": summary["passed"], "avg_score": summary["avg_score"],
        })
    except Exception:
        pass

    return summary


def _check_identity_leak(chunks: list[dict], response: str) -> None:
    """Log warning if identity-tier content appears in cloud-eligible response."""
    identity_chunks = [c for c in chunks if c["tier"] == MemoryTier.CORE.value]
    if identity_chunks:
        log.info(
            "E-21 identity-leak probe: %d identity-tier chunks in retrieval. "
            "Verify cloud routing strips these before dispatch.",
            len(identity_chunks),
        )


def _build_summary(results: list[EvalResult], run_id: str, ts: datetime) -> dict:
    """Build aggregate summary from individual eval results."""
    if not results:
        return {
            "run_id": run_id, "timestamp": ts.isoformat(),
            "total": 0, "passed": 0, "marginal": 0, "failed": 0,
            "avg_score": 0.0, "avg_precision": 0.0, "avg_recall": 0.0,
            "tier_mismatches": 0, "results": [],
        }

    passed = sum(1 for r in results if r.verdict == EvalVerdict.PASS.value)
    marginal = sum(1 for r in results if r.verdict == EvalVerdict.MARGINAL.value)
    failed = sum(1 for r in results if r.verdict == EvalVerdict.FAIL.value)
    tier_mismatches = sum(1 for r in results if r.tier_mismatch)

    return {
        "run_id": run_id,
        "timestamp": ts.isoformat(),
        "total": len(results),
        "passed": passed,
        "marginal": marginal,
        "failed": failed,
        "avg_score": round(sum(r.overall_score for r in results) / len(results), 3),
        "avg_precision": round(sum(r.context_precision for r in results) / len(results), 3),
        "avg_recall": round(sum(r.context_recall for r in results) / len(results), 3),
        "tier_mismatches": tier_mismatches,
        "results": [r.model_dump() for r in results],
    }
