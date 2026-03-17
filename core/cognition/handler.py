"""Handler orchestration — wires PII, routing, inference, credits, response."""

from __future__ import annotations

import logging
import re
import threading

from datetime import datetime, timezone
from typing import Iterator, NamedTuple

from core.identity.input_guard import detect_adversarial
from core.cognition.compiler import compile_context, render_context
from core.autonomic.confidence import score_response
from core.interface.config import CLOUD_MAX_TOKENS, DEFAULT_TOKEN_BUDGET, INFERENCE_MODEL
from core.interface.settings import get_setting
from core.safety.credits import charge, check_hard_ceiling, load_credits
from core.cognition.inference import (
    check_inference_model,
    check_logprob_support,
    generate_local,
    generate_local_stream,
    load_system_prompt,
)
from core.interface.models import (
    CompiledContext,
    ConfidenceResult,
    ContradictionResult,
    InferenceResponse,
    PIIResult,
    RoutingDecision,
    RouteType,
)
from core.safety.pii import detect_pii, log_detection, scrub_pii
from core.cognition.routing import log_routing_decision, query_hash, route_query
from core.memory.session import get_or_create_session, log_interaction, log_interaction_complete

log = logging.getLogger(__name__)

_MISSION_KEYWORDS = frozenset({
    "give up", "giving up", "quit", "quitting", "abandon", "stop pursuing",
    "corporate", "promotion", "safe path", "day job", "settle",
    "stop", "pause indefinitely", "not worth it",
})

# T-037: Provider registry (lazy-initialized, thread-safe)
_provider_registry = None
_provider_router = None
_registry_lock = threading.Lock()
_router_lock = threading.Lock()


def get_provider_registry():
    """Get or create the global ProviderRegistry (thread-safe)."""
    global _provider_registry
    if _provider_registry is None:
        with _registry_lock:
            if _provider_registry is None:
                from core.cognition.providers.bootstrap import create_registry
                _provider_registry = create_registry()
    return _provider_registry


def get_provider_router():
    """Get or create the global PrivacyAwareRouter (thread-safe)."""
    global _provider_router
    if _provider_router is None:
        with _router_lock:
            if _provider_router is None:
                from core.cognition.providers.router import PrivacyAwareRouter
                from core.interface.models import RoutingPosture
                posture_str = str(get_setting("cloud_routing_posture")).lower()
                try:
                    posture = RoutingPosture(posture_str)
                except ValueError:
                    log.warning("Invalid routing posture '%s' — defaulting to balanced", posture_str)
                    posture = RoutingPosture.BALANCED
                # OPT-01: Load model tiers from providers.toml
                from core.cognition.providers.config_loader import load_providers_config, ConfigError
                try:
                    config = load_providers_config()
                    model_tiers = config.get("model_tiers")
                except ConfigError:
                    model_tiers = None

                _provider_router = PrivacyAwareRouter(
                    registry=get_provider_registry(),
                    posture=posture,
                    model_tiers=model_tiers,
                )
    return _provider_router


class PreparedContext(NamedTuple):
    decision: RoutingDecision
    pii_result: PIIResult
    effective_query: str
    pii_scrubbed: bool
    compiled: CompiledContext
    context_block: str
    system_prompt: str | None
    full_prompt: str
    session: dict
    qhash: str


class PostProcessResult(NamedTuple):
    text: str
    confidence: ConfidenceResult
    contradiction: ContradictionResult | None
    warnings: list[str]
    is_hard_veto: bool


# Matches classifier JSON that bleeds into model output (e.g. assertion checker)
_JSON_PREAMBLE_RE = re.compile(
    r'^\s*\{[^{}]*"(?:contains_assertion|assertion_type|is_coherent|coherence_score|response)"[^{}]*\}\s*',
)


def _strip_json_preamble(text: str) -> str:
    """Remove classifier JSON that occasionally bleeds into model output."""
    cleaned = _JSON_PREAMBLE_RE.sub("", text, count=1)
    return cleaned if cleaned.strip() else text


def _prepare_query(
    query: str,
    force_local: bool = False,
    force_cloud: bool = False,
    skip_pii_scrub: bool = False,
    source: str = "handler",
) -> PreparedContext | InferenceResponse:
    """Steps 0-5: validate, session, FSM, adversarial, PII, context, routing."""
    if not query or not query.strip():
        return InferenceResponse(
            text="[EMPTY QUERY] No input provided.",
            route=RouteType.LOCAL,
            model_used=INFERENCE_MODEL,
            confidence=0.0,
            pii_scrubbed=False,
        )

    qhash = query_hash(query)

    # 0. Session tracking
    session = get_or_create_session()
    log_interaction(session["session_id"], session["started_at"], qhash, query, source=source)

    # 0b. FSM auto-transition (non-blocking)
    try:
        from core.autonomic.fsm import get_current_state, transition_to
        from core.interface.models import SystemState
        if get_current_state() in (SystemState.IDLE, SystemState.ASLEEP):
            transition_to(SystemState.ACTIVE, trigger="auto:query")
    except Exception:
        pass  # FSM failure must never block queries

    # 0c. Adversarial input detection
    adv_result = detect_adversarial(query)
    if adv_result.is_adversarial:
        log.warning(
            "[ADVERSARIAL QUERY] severity=%d patterns=%s",
            adv_result.severity, adv_result.matched_patterns,
        )
        if adv_result.severity >= 6:
            return InferenceResponse(
                text=f"[ADVERSARIAL INPUT REJECTED]\n\nSeverity: {adv_result.severity}/10\nPatterns: {', '.join(adv_result.matched_patterns)}\n\nThe system detected an attempt to manipulate core identity or bypass constraints. Query rejected.",
                route=RouteType.LOCAL,
                model_used=INFERENCE_MODEL,
                confidence=0.0,
                pii_scrubbed=False,
            )

    # 1. PII detection
    if skip_pii_scrub:
        pii_result = PIIResult(has_pii=False, entities=[])
    else:
        pii_result = detect_pii(query)
        if pii_result.has_pii:
            log_detection(pii_result, qhash)

    # 2. Determine effective query
    effective_query = query
    pii_scrubbed = False
    if pii_result.has_pii:
        scrub_result = scrub_pii(query)
        if scrub_result.scrubbed_text and scrub_result.scrubbed_text != query:
            effective_query = scrub_result.scrubbed_text
            pii_scrubbed = True

    # 3. Compile context
    try:
        compiled = compile_context(effective_query, token_budget=int(get_setting("default_token_budget")))
        context_block = render_context(compiled)
    except (ValueError, RuntimeError, OSError) as e:
        log.warning("Context compilation failed: %s", e)
        context_block = "(no context available)"
        compiled = CompiledContext(query=effective_query, slices=[], total_tokens=0, budget=DEFAULT_TOKEN_BUDGET)

    # 4. Assemble prompt
    system_prompt = load_system_prompt("sovereign")
    full_prompt = f"{context_block}\n\n---\nQuery: {effective_query}"

    # 4b. Complexity pre-score
    complexity = None
    if not force_local:
        try:
            from core.cognition.complexity import score_complexity
            complexity = score_complexity(effective_query)
        except (ValueError, RuntimeError) as e:
            log.warning("Complexity scoring failed: %s", e)

    # 5. Route decision
    if force_local:
        decision = RoutingDecision(
            route=RouteType.LOCAL,
            reason="Forced local by user flag",
            confidence=None,
            pii_detected=pii_result.has_pii,
            query_hash=qhash,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
    elif force_cloud:
        decision = RoutingDecision(
            route=RouteType.CLOUD,
            reason="Forced cloud by user flag",
            confidence=None,
            pii_detected=pii_result.has_pii,
            query_hash=qhash,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
    else:
        query_vec = None
        try:
            from core.memory.embedder import embed_single
            query_vec = embed_single(effective_query)
        except (ConnectionError, RuntimeError):
            pass
        decision = route_query(effective_query, pii_result, None, query_vector=query_vec, complexity=complexity)

    return PreparedContext(
        decision=decision,
        pii_result=pii_result,
        effective_query=effective_query,
        pii_scrubbed=pii_scrubbed,
        compiled=compiled,
        context_block=context_block,
        system_prompt=system_prompt,
        full_prompt=full_prompt,
        session=session,
        qhash=qhash,
    )


def _post_process(
    response_text: str,
    logprobs: object | None,
    ctx: PreparedContext,
    model_used: str,
) -> PostProcessResult:
    """Steps 7-8c: confidence, assertions, NLI, coherence, output filter."""
    text = _strip_json_preamble(response_text)
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

    # 8. NLI contradiction check
    contradiction = None
    _query_lower = ctx.effective_query.lower()
    nli_trigger = (
        ctx.decision.cosine_gate_fired
        or "Force-local" in ctx.decision.reason
        or any(kw in _query_lower for kw in _MISSION_KEYWORDS)
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

    # 8b. Coherence check (skip if already vetoed)
    if not is_hard_veto:
        try:
            from core.identity.coherence import check_coherence
            coherence = check_coherence(text, query=ctx.effective_query)

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
    text = _strip_json_preamble(text)

    # 8c. Output sensitivity filter
    try:
        from core.safety.output_filter import check_output_sensitivity
        filter_result = check_output_sensitivity(text)
        text = filter_result.response
        if filter_result.level != "CLEAN":
            log.warning("[OUTPUT FILTER] level=%s triggered=%s",
                        filter_result.level, filter_result.triggered)
    except (ImportError, ValueError, RuntimeError) as e:
        log.warning("[OUTPUT FILTER] failed: %s — passing through", e)

    return PostProcessResult(
        text=text,
        confidence=confidence,
        contradiction=contradiction,
        warnings=warnings,
        is_hard_veto=is_hard_veto,
    )


def _filter_cloud_context(compiled: CompiledContext) -> str:
    """Render context excluding CORE and EPISODIC tiers for cloud dispatch."""
    cloud_slices = [s for s in compiled.slices if s.name not in ("core", "episodic")]
    cloud_compiled = CompiledContext(
        query=compiled.query,
        slices=cloud_slices,
        total_tokens=sum(s.token_count for s in cloud_slices),
        budget=compiled.budget,
    )
    return render_context(cloud_compiled)


def _check_cloud_gate(
    prep: PreparedContext,
    decision: RoutingDecision,
    streamed: bool = False,
) -> tuple[RoutingDecision, bool]:
    """PII hard-gate + credit ceiling check for cloud routes.

    Returns (updated_decision, pii_blocked). If either check fails, decision is
    downgraded to LOCAL and pii_blocked is True when PII caused the block.
    """
    suffix = " (streamed)" if streamed else ""
    pii_blocked = prep.pii_result.has_pii and not prep.pii_scrubbed

    if pii_blocked:
        log.error("PII scrub failed but cloud route selected — aborting cloud%s", suffix)
        return (
            RoutingDecision(
                route=RouteType.LOCAL,
                reason=f"PII hard-gate abort{suffix}",
                confidence=None,
                pii_detected=True,
                query_hash=prep.qhash,
                timestamp=decision.timestamp,
            ),
            True,
        )

    estimated_max_tokens = DEFAULT_TOKEN_BUDGET + CLOUD_MAX_TOKENS
    if check_hard_ceiling(amount=estimated_max_tokens):
        log.warning("[PRE-FLIGHT CEILING CHECK: CLOUD BLOCKED]%s estimated=%d", suffix, estimated_max_tokens)
        return (
            RoutingDecision(
                route=RouteType.LOCAL,
                reason=f"Credit hard ceiling pre-flight{suffix} (fallback)",
                confidence=None,
                pii_detected=prep.pii_result.has_pii,
                query_hash=prep.qhash,
                timestamp=decision.timestamp,
            ),
            False,
        )

    return decision, False


def execute_query(
    query: str,
    force_local: bool = False,
    force_cloud: bool = False,
    skip_pii_scrub: bool = False,
    cloud_name: str | None = None,
    model_override: str | None = None,
) -> InferenceResponse:
    """Full query pipeline: session -> PII -> context -> inference -> confidence -> routing -> response."""
    prep = _prepare_query(query, force_local, force_cloud, skip_pii_scrub, source="handler")
    if isinstance(prep, InferenceResponse):
        return prep

    from core.autonomic.daemon import inference_active

    with inference_active():
        return _execute_query_inner(prep)


def _execute_query_inner(prep: PreparedContext) -> InferenceResponse:
    """Inference execution (runs inside inference_active guard)."""
    try:
        from core.autonomic.events import emit_event
        emit_event("inference", "start", {"route": prep.decision.route.value, "query_hash": prep.qhash})
    except Exception:
        pass

    # 6. Execute inference based on route
    raw = None
    cloud_model = INFERENCE_MODEL
    decision = prep.decision

    if decision.route == RouteType.CLOUD:
        decision, _ = _check_cloud_gate(prep, decision)

    # T-037: Provider system dispatch (after PII gate, when non-local provider is configured)
    provider_default = str(get_setting("provider_default"))
    pii_blocked = prep.pii_result.has_pii and not prep.pii_scrubbed
    # cloud_context is computed lazily and cached here to avoid calling _filter_cloud_context
    # more than once per request (previously called in both provider path and legacy cloud path)
    _cloud_context_cache: list[str] = []  # use list so inner functions can assign

    def _get_cloud_context() -> str:
        if not _cloud_context_cache:
            _cloud_context_cache.append(_filter_cloud_context(prep.compiled))
        return _cloud_context_cache[0]

    if raw is None and not pii_blocked and (provider_default != "local" or decision.route == RouteType.CLOUD):
        try:
            router = get_provider_router()
            from core.interface.models import ProviderMessage
            cloud_context = _get_cloud_context()
            filtered_prompt = f"{cloud_context}\n\n---\nQuery: {prep.effective_query}" if cloud_context else prep.effective_query
            msgs = []
            if prep.system_prompt:
                msgs.append(ProviderMessage(role="system", content=prep.system_prompt))
            msgs.append(ProviderMessage(role="user", content=filtered_prompt))

            target_provider = cloud_name or (str(get_setting("provider_cloud_default")) if decision.route == RouteType.CLOUD else None)
            route_kwargs = {}
            if model_override:
                route_kwargs["model"] = model_override
            result = router.route(msgs, provider=target_provider, **route_kwargs)

            # OPT-06: Log query cost
            try:
                from core.cognition.providers.cost_tracker import CostTracker
                config = load_providers_config()
                CostTracker(rates=config.get("costs")).log_query(
                    provider=result.provider, model=result.model,
                    input_tokens=result.input_tokens, output_tokens=result.output_tokens,
                    latency_ms=result.latency_ms,
                )
            except Exception:
                pass  # Cost tracking is best-effort, never blocks inference

            if "[INFERENCE ERROR" not in result.text:
                raw = {"response": result.text, "logprobs": None}
                cloud_model = result.model
                if result.provider != "ollama":
                    charge(result.input_tokens + result.output_tokens, f"cloud:{result.model}")
            # else: fall through to existing local path
        except Exception as e:
            log.error("Provider system dispatch failed: %s — falling back to legacy path", e)

    # Legacy cloud path (only if T-037 did not handle it)
    if raw is None and decision.route == RouteType.CLOUD and not pii_blocked:
        from core.cognition.cloud import send_to_cloud
        try:
            cloud_resp = send_to_cloud(prep.effective_query, _get_cloud_context(), system=prep.system_prompt)
            raw = {"response": cloud_resp.text, "logprobs": None}
            cloud_model = cloud_resp.model
            charge(cloud_resp.input_tokens + cloud_resp.output_tokens, f"cloud:{cloud_resp.model}")
        except Exception as e:
            log.error("Cloud dispatch failed: %s — falling back to local", e)
            decision = RoutingDecision(
                route=RouteType.LOCAL, reason=f"Cloud fallback: {e}",
                confidence=None, pii_detected=prep.pii_result.has_pii,
                query_hash=prep.qhash, timestamp=decision.timestamp,
            )

    if raw is None:
        raw = generate_local(prep.full_prompt, system=prep.system_prompt or None)
        if "error" in raw:
            log.error("Inference error: %s", raw["error"])
            return InferenceResponse(
                text=f"[INFERENCE ERROR: {raw['error']}]",
                route=RouteType.LOCAL, model_used=INFERENCE_MODEL,
                confidence=0.0, pii_scrubbed=prep.pii_scrubbed,
            )

    # Use updated decision (may have changed due to fallbacks)
    ctx = prep._replace(decision=decision)
    result = _post_process(raw["response"], raw.get("logprobs"), ctx, cloud_model)
    log_routing_decision(decision)

    effective_model = cloud_model if decision.route == RouteType.CLOUD else INFERENCE_MODEL
    resp = InferenceResponse(
        text=result.text,
        route=decision.route,
        model_used=effective_model,
        confidence=result.confidence.score,
        pii_scrubbed=prep.pii_scrubbed,
        routing_decision=decision,
        contradiction=result.contradiction,
    )
    log_interaction_complete(ctx.session["session_id"], ctx.session["started_at"], ctx.qhash, resp)

    try:
        from core.autonomic.events import emit_event
        emit_event("inference", "complete", {
            "route": decision.route.value, "model": effective_model,
            "confidence": result.confidence.score, "query_hash": prep.qhash,
        })
    except Exception:
        pass

    return resp


def execute_query_stream(
    query: str,
    force_local: bool = False,
    force_cloud: bool = False,
    skip_pii_scrub: bool = False,
    cloud_name: str | None = None,
    model_override: str | None = None,
) -> Iterator[dict]:
    """Streaming variant. Yields {"delta": str, "done": bool, "response": InferenceResponse | None}."""
    # Validate model override before any work
    if model_override:
        from core.cognition.inference import validate_model_name
        err = validate_model_name(model_override)
        if err:
            yield {"delta": f"[MODEL ERROR] {err}", "done": False, "response": None}
            yield {"delta": "", "done": True, "response": InferenceResponse(
                text=f"[MODEL ERROR] {err}", route=RouteType.LOCAL,
                model_used=model_override, confidence=0.0, pii_scrubbed=False,
            )}
            return

    prep = _prepare_query(query, force_local, force_cloud, skip_pii_scrub, source="stream")
    if isinstance(prep, InferenceResponse):
        yield {"delta": prep.text, "done": False, "response": None}
        yield {"delta": "", "done": True, "response": prep}
        return

    import core.autonomic.daemon as _daemon
    _daemon._inference_active = True

    # Apply model override: if it matches cloud model, force cloud route
    if model_override:
        from core.interface.config import CLOUD_MODEL
        if model_override == CLOUD_MODEL:
            prep = prep._replace(
                decision=RoutingDecision(
                    route=RouteType.CLOUD, reason="Model override (cloud)",
                    confidence=None, pii_detected=prep.pii_result.has_pii,
                    query_hash=prep.qhash, timestamp=prep.decision.timestamp,
                ),
            )

    try:
        yield from _execute_stream_inner(prep, model_override=model_override)
    finally:
        _daemon._inference_active = False


def _execute_stream_inner(prep: PreparedContext, model_override: str | None = None) -> Iterator[dict]:
    """Stream inference (runs inside inference_active guard)."""
    try:
        from core.autonomic.events import emit_event
        emit_event("inference", "start", {"route": prep.decision.route.value, "query_hash": prep.qhash, "stream": True})
    except Exception:
        pass

    accumulated = []
    use_cloud = prep.decision.route == RouteType.CLOUD
    effective_model = model_override or str(get_setting("inference_model"))
    decision = prep.decision

    if use_cloud:
        decision, _ = _check_cloud_gate(prep, decision, streamed=True)
        use_cloud = decision.route == RouteType.CLOUD

    # T-037: Provider system streaming (after PII gate, when non-local provider)
    provider_default = str(get_setting("provider_default"))
    pii_blocked = prep.pii_result.has_pii and not prep.pii_scrubbed
    # cloud_context is computed lazily and cached to avoid calling _filter_cloud_context
    # more than once per request (previously called in both provider path and legacy cloud path)
    _stream_cloud_ctx_cache: list[str] = []

    def _get_stream_cloud_context() -> str:
        if not _stream_cloud_ctx_cache:
            _stream_cloud_ctx_cache.append(_filter_cloud_context(prep.compiled))
        return _stream_cloud_ctx_cache[0]

    provider_streamed = False
    if not pii_blocked and (use_cloud or provider_default != "local"):
        try:
            router = get_provider_router()
            from core.interface.models import ProviderMessage
            cloud_context = _get_stream_cloud_context()
            filtered_prompt = f"{cloud_context}\n\n---\nQuery: {prep.effective_query}" if cloud_context else prep.effective_query
            msgs = []
            if prep.system_prompt:
                msgs.append(ProviderMessage(role="system", content=prep.system_prompt))
            msgs.append(ProviderMessage(role="user", content=filtered_prompt))

            target_provider = cloud_name or (str(get_setting("provider_cloud_default")) if use_cloud else None)
            route_kwargs = {}
            if model_override:
                route_kwargs["model"] = model_override
            for delta in router.route_stream(msgs, provider=target_provider, **route_kwargs):
                accumulated.append(delta)
                yield {"delta": delta, "done": False, "response": None}
                provider_streamed = True

            if provider_streamed:
                use_cloud = False  # prevent legacy cloud path
                effective_model = cloud_name or provider_default
                # Charge estimated tokens for streamed cloud calls
                if effective_model != "local":
                    streamed_text = "".join(accumulated)
                    estimated_tokens = int(len(streamed_text.split()) * 1.3) * 2  # rough in+out
                    charge(estimated_tokens, f"cloud:{effective_model}")
        except Exception as e:
            log.error("Provider stream failed: %s — falling back to legacy path", e)

    if use_cloud:
        from core.cognition.cloud import stream_cloud
        try:
            from core.interface.config import CLOUD_MODEL
            effective_model = CLOUD_MODEL
            for delta in stream_cloud(prep.effective_query, _get_stream_cloud_context(), system=prep.system_prompt):
                accumulated.append(delta)
                yield {"delta": delta, "done": False, "response": None}
        except Exception as e:
            log.error("Cloud stream failed: %s — falling back to local", e)
            accumulated = []
            use_cloud = False
            effective_model = INFERENCE_MODEL

    if not use_cloud and not provider_streamed:
        preamble_buf = ""
        preamble_done = False
        for chunk in generate_local_stream(prep.full_prompt, system=prep.system_prompt or None, model=effective_model):
            accumulated.append(chunk["delta"])
            if not chunk["done"]:
                if not preamble_done:
                    preamble_buf += chunk["delta"]
                    # Buffer until we see non-whitespace after a potential JSON block
                    if "}" in preamble_buf:
                        cleaned = _strip_json_preamble(preamble_buf)
                        if cleaned != preamble_buf:
                            log.info("Stripped JSON preamble from stream")
                        if cleaned.strip():
                            yield {"delta": cleaned, "done": False, "response": None}
                        preamble_done = True
                    elif len(preamble_buf) > 500 or (preamble_buf.lstrip() and not preamble_buf.lstrip().startswith("{")):
                        # Not a JSON preamble — flush buffer as-is
                        yield {"delta": preamble_buf, "done": False, "response": None}
                        preamble_done = True
                else:
                    yield {"delta": chunk["delta"], "done": False, "response": None}

    full_text = "".join(accumulated)

    ctx = prep._replace(decision=decision)
    result = _post_process(full_text, None, ctx, effective_model)

    for w in result.warnings:
        yield {"delta": w, "done": False, "response": None}

    log_routing_decision(decision)

    resp = InferenceResponse(
        text=result.text,
        route=decision.route,
        model_used=effective_model,
        confidence=result.confidence.score,
        pii_scrubbed=prep.pii_scrubbed,
        routing_decision=decision,
        contradiction=result.contradiction,
    )
    log_interaction_complete(ctx.session["session_id"], ctx.session["started_at"], ctx.qhash, resp)

    try:
        from core.autonomic.events import emit_event
        emit_event("inference", "complete", {
            "route": decision.route.value, "model": effective_model,
            "confidence": result.confidence.score, "query_hash": prep.qhash, "stream": True,
        })
    except Exception:
        pass

    yield {"delta": "", "done": True, "response": resp}
