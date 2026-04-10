"""Post-inference processing: confidence, assertions, NLI, coherence, output filter."""

from __future__ import annotations

import logging

from core.autonomic.confidence import score_response
from core.cognition.pipeline import (
    PreparedContext, PostProcessResult, strip_json_preamble, MISSION_KEYWORDS,
)
from core.cognition.pipeline.trace import RoutingTrace
from core.interface.models import ConfidenceResult

log = logging.getLogger(__name__)


def post_process(
    response_text: str,
    logprobs: object | None,
    ctx: PreparedContext,
    model_used: str,
    trace: RoutingTrace | None = None,
    skip_nli: bool = False,
) -> PostProcessResult:
    """Steps 7-8c: confidence, assertions, NLI, coherence, output filter."""
    text = strip_json_preamble(response_text)
    warnings: list[str] = []
    is_hard_veto = False

    # 7. Score confidence
    confidence = score_response(text, logprobs)

    # 8a. Assertion extraction
    try:
        from core.identity.assertions import check_assertion, log_assertion
        assertion = check_assertion(ctx.effective_query)
        if assertion.contains_assertion:
            if assertion.vault_chunks:
                from core.identity.contradiction import check_contradiction
                assertion_nli = check_contradiction(assertion.extracted_claim, assertion.vault_chunks)
                log_assertion(ctx.session["session_id"], assertion, "conflict", assertion_nli)
                if assertion_nli.has_contradiction and assertion_nli.confidence >= 60:
                    log.warning("[ASSERTION] vault conflict detected claim=%r", assertion.extracted_claim)
                    warning = (
                        f"\n\n[NOTE: Your assertion '{assertion.extracted_claim}' may conflict "
                        f"with recorded vault data. Verify before updating canon.]"
                    )
                    text += warning
                    warnings.append(warning)
            else:
                log_assertion(ctx.session["session_id"], assertion, "new", None)
    except (ImportError, ValueError, RuntimeError) as e:
        log.warning("[ASSERTION] check failed: %s — passing through", e)

    # 8. NLI contradiction check (skip when routed via OAuth provider — no KAIROS persona)
    #    T-120b: Also skip when caller explicitly requests it (e.g. gauntlet probes)
    _is_oauth_provider = "anthropic-oauth" in (ctx.decision.reason or "")
    contradiction = None
    _query_lower = ctx.effective_query.lower()
    nli_trigger = (
        not skip_nli
        and not _is_oauth_provider
        and (
            ctx.decision.cosine_gate_fired
            or "Force-local" in ctx.decision.reason
            or any(kw in _query_lower for kw in MISSION_KEYWORDS)
        )
    )
    if nli_trigger:
        try:
            from core.memory.search import hybrid_search
            from core.identity.contradiction import check_contradiction
            from core.interface.models import MemoryTier

            sovereign_chunks = hybrid_search(ctx.effective_query, limit=5, tier_filter=MemoryTier.CORE)
            chunks = [{"source_path": c.source_path, "content": c.content} for c in sovereign_chunks]
            contradiction = check_contradiction(text, chunks)

            if contradiction and contradiction.has_contradiction:
                if contradiction.contradiction_type == "identity" and contradiction.confidence >= 60:
                    log.error("IDENTITY CONTRADICTION — vetoing response")
                    text = "[HARD VETO] Response contradicts sovereign identity data. Possible hallucination."
                    confidence = ConfidenceResult(score=0.0, method=confidence.method + "+identity_veto")
                    is_hard_veto = True
                    warnings.append("\n\n[SYSTEM OVERRIDE: IDENTITY CONTRADICTION DETECTED. RESPONSE INVALID.]")
                elif contradiction.contradiction_type == "knowledge" and contradiction.confidence >= 60:
                    confidence = ConfidenceResult(
                        score=max(0, confidence.score - 20),
                        method=confidence.method + "+nli_penalty",
                        hedging_flags=(confidence.hedging_flags or []) + ["KNOWLEDGE_CONTRADICTION"],
                    )
        except (ImportError, ValueError, RuntimeError) as e:
            log.warning("NLI check failed: %s — passing through", e)

    # 8b. Coherence check (skip if already vetoed or OAuth provider)
    if not is_hard_veto and not _is_oauth_provider:
        try:
            from core.identity.coherence import check_coherence
            coherence = check_coherence(text)

            if not coherence.is_coherent:
                if coherence.warning_message and "[HARD VETO" in coherence.warning_message:
                    log.error("CRITICAL COHERENCE FAILURE — hard veto")
                    text = coherence.warning_message
                    confidence = ConfidenceResult(score=0.0, method=confidence.method + "+coherence_hard_veto")
                    is_hard_veto = True
                    warnings.append(f"\n\n{coherence.warning_message}")
                elif coherence.warning_message and "[SOFT VETO" in coherence.warning_message:
                    text = f"{text}\n\n{coherence.warning_message}"
                    confidence = ConfidenceResult(
                        score=0.0,
                        method=confidence.method + "+coherence_veto",
                        hedging_flags=(confidence.hedging_flags or []) + ["FOREIGN_PERSONA"],
                    )
                    warnings.append(f"\n\n{coherence.warning_message}")
                    log.warning("HIGH COHERENCE FAILURE — soft veto, confidence=0")
                else:
                    text = f"{text}\n\n{coherence.warning_message}"
                    warnings.append(f"\n\n{coherence.warning_message}")
                    log.info("MODERATE COHERENCE WARNING")
        except (ImportError, ValueError, RuntimeError) as e:
            log.warning("Coherence check failed: %s — passing through", e)

    # 8b-post. Second-pass JSON preamble strip (catches leaks that survived first pass)
    text = strip_json_preamble(text)

    # 8c. Output sensitivity filter
    try:
        from core.safety.output_filter import check_output_sensitivity
        filter_result = check_output_sensitivity(text)
        text = filter_result.response
        if filter_result.level != "CLEAN":
            log.warning("[OUTPUT FILTER] level=%s triggered=%s",
                        filter_result.level, filter_result.triggered)
            if trace is not None:
                trace.output_filtered = True
            # T-119: emit notification event for output filter activation (MUST tier)
            try:
                from core.autonomic.events import emit_event
                emit_event("safety", "output_filter_activated", {
                    "level": filter_result.level,
                    "triggered": filter_result.triggered,
                })
            except Exception as e:
                log.debug("output_filter_activated emit suppressed: %s", e)
    except (ImportError, ValueError, RuntimeError) as e:
        log.warning("[OUTPUT FILTER] failed: %s — passing through", e)

    return PostProcessResult(
        text=text,
        confidence=confidence,
        contradiction=contradiction,
        warnings=warnings,
        is_hard_veto=is_hard_veto,
    )
