"""Inference dispatch — blocking and streaming execution paths.

NEVER_LEAVE gate points in this module:
1. Legacy cloud streaming path (~line in dispatch_streaming): ContentClassifier check
   before send_to_cloud/stream_cloud — blocks NEVER_LEAVE content from legacy Gemini bridge.
2. check_cloud_gate(): PII hard-gate aborts cloud when unscrubbed PII detected.
3. Credit ceiling pre-flight in check_cloud_gate().

The model-override NEVER_LEAVE check lives in handler.py (execute_query_stream),
NOT here — it runs before dispatch is called.
"""

from __future__ import annotations

import logging
import threading
from typing import Iterator

from core.cognition.pipeline.trace import RoutingTrace
from core.cognition.compiler import render_context
from core.cognition.inference import generate_local, generate_local_stream
from core.cognition.pipeline import PreparedContext, strip_json_preamble
from core.cognition.pipeline.postprocess import post_process
from core.cognition.routing import log_routing_decision
from core.interface.config import CLOUD_MAX_TOKENS, DEFAULT_TOKEN_BUDGET, INFERENCE_MODEL
from core.interface.models import (
    CompiledContext,
    InferenceResponse,
    RoutingDecision,
    RouteType,
)
from core.interface.settings import get_setting
from core.memory.session import log_interaction_complete
from core.safety.credits import charge, check_hard_ceiling

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helper: resolve generation parameters (Room > Global)
# ---------------------------------------------------------------------------

def resolve_generation_params(room=None) -> tuple[float, int]:
    """Resolve temperature and max_tokens: Room > Global."""
    temperature = float(get_setting("inference_temperature"))
    max_tokens = int(get_setting("inference_max_tokens"))

    if room is not None:
        if room.voice.temperature is not None:
            temperature = room.voice.temperature
        if room.limits.max_tokens_per_query is not None:
            max_tokens = room.limits.max_tokens_per_query

    return temperature, max_tokens


# ---------------------------------------------------------------------------
# Helper: model → provider mapping
# ---------------------------------------------------------------------------

def infer_provider_for_model(model: str | None) -> str | None:
    """Return the correct provider name for a model override, or None for default."""
    if model and model.startswith("claude-"):
        return "anthropic-oauth"
    return None


# ---------------------------------------------------------------------------
# Provider registry / router (lazy-initialized, thread-safe)
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Cloud context filter
# ---------------------------------------------------------------------------

def filter_cloud_context(compiled: CompiledContext) -> str:
    """Render context excluding CORE and EPISODIC tiers for cloud dispatch."""
    cloud_slices = [s for s in compiled.slices if s.name not in ("core", "episodic")]
    cloud_compiled = CompiledContext(
        query=compiled.query,
        slices=cloud_slices,
        total_tokens=sum(s.token_count for s in cloud_slices),
        budget=compiled.budget,
    )
    return render_context(cloud_compiled)


# ---------------------------------------------------------------------------
# Cloud gate (PII + credit ceiling)
# ---------------------------------------------------------------------------

def check_cloud_gate(
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


# ---------------------------------------------------------------------------
# Blocking dispatch (stage 6)
# ---------------------------------------------------------------------------

def dispatch_blocking(
    prep: PreparedContext,
    model_override: str | None = None,
    cloud_name: str | None = None,
    trace: RoutingTrace | None = None,
    skip_nli: bool = False,
) -> InferenceResponse:
    """Blocking inference execution (runs inside inference_active guard)."""
    try:
        from core.autonomic.events import emit_event
        emit_event("inference", "start", {"route": prep.decision.route.value, "query_hash": prep.qhash})
    except Exception as e:
        log.debug("inference start emit_event suppressed: %s", e)

    raw = None
    cloud_model = INFERENCE_MODEL
    decision = prep.decision

    if decision.route == RouteType.CLOUD:
        decision, _ = check_cloud_gate(prep, decision)

    # T-037: Provider system dispatch (after PII gate, when non-local provider is configured)
    provider_default = str(get_setting("provider_default"))
    pii_blocked = prep.pii_result.has_pii and not prep.pii_scrubbed
    _cloud_context_cache: list[str] = []

    def _get_cloud_context() -> str:
        if not _cloud_context_cache:
            _cloud_context_cache.append(filter_cloud_context(prep.compiled))
        return _cloud_context_cache[0]

    # Check room for cloud provider override (must happen before routing gate)
    _room_provider_sync = None
    _room_model_sync = None
    _room_allowed_providers = None
    _room_ref = None
    _forced_local = "force" in (decision.reason or "").lower()
    try:
        from core.rooms.manager import get_room_manager
        room = get_room_manager().get_active_room()
        _room_ref = room
        _room_allowed_providers = room.allowed_providers
        if not model_override and not _forced_local:
            if room.model.model:
                _room_model_sync = room.model.model
            if room.model.provider:
                _room_provider_sync = room.model.provider
    except (ImportError, ValueError):
        pass

    _gen_temp, _gen_max_tokens = resolve_generation_params(_room_ref)
    _global_temp = float(get_setting("inference_temperature"))
    _global_max_tokens = int(get_setting("inference_max_tokens"))
    if trace is not None:
        if _gen_temp != _global_temp:
            trace.room_temperature = _gen_temp
        if _gen_max_tokens != _global_max_tokens:
            trace.room_max_tokens = _gen_max_tokens

    # Room with a cloud provider forces cloud route
    if _room_provider_sync and _room_provider_sync != "ollama" and not pii_blocked:
        decision = decision.model_copy(update={"route": RouteType.CLOUD})

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
            route_kwargs["temperature"] = _gen_temp
            route_kwargs["max_tokens"] = (
                min(_gen_max_tokens, CLOUD_MAX_TOKENS)
                if decision.route == RouteType.CLOUD
                else _gen_max_tokens
            )

            # Room model/provider override (only when no explicit model_override)
            if not model_override:
                if _room_model_sync:
                    route_kwargs["model"] = _room_model_sync
                if _room_provider_sync and not pii_blocked:
                    target_provider = _room_provider_sync

            if model_override:
                route_kwargs["model"] = model_override
                target_provider = infer_provider_for_model(model_override) or target_provider
            result = router.route(msgs, provider=target_provider, allowed_providers=_room_allowed_providers, **route_kwargs)

            # OPT-06: Log query cost
            try:
                from core.cognition.providers.config_loader import load_providers_config
                from core.cognition.providers.cost_tracker import CostTracker
                config = load_providers_config()
                CostTracker(rates=config.get("costs")).log_query(
                    provider=result.provider, model=result.model,
                    input_tokens=result.input_tokens, output_tokens=result.output_tokens,
                    latency_ms=result.latency_ms,
                )
            except Exception as e:
                log.debug("cost tracking suppressed: %s", e)

            if "[INFERENCE ERROR" not in result.text:
                raw = {"response": result.text, "logprobs": None}
                cloud_model = result.model
                if trace is not None:
                    trace.provider = result.provider
                    trace.model = result.model
                if result.provider != "ollama":
                    charge(result.input_tokens + result.output_tokens, f"cloud:{result.model}")
            # else: fall through to existing local path
        except Exception as e:
            log.error("Provider system dispatch failed: %s — falling back to legacy path", e)

    # Legacy cloud path (only if T-037 did not handle it, and room allows gemini)
    _legacy_cloud_allowed = _room_allowed_providers is None or "gemini" in _room_allowed_providers
    if raw is None and decision.route == RouteType.CLOUD and not pii_blocked and _legacy_cloud_allowed:
        from core.cognition.cloud import send_to_cloud
        try:
            cloud_resp = send_to_cloud(prep.effective_query, _get_cloud_context(), system=prep.system_prompt)
            raw = {"response": cloud_resp.text, "logprobs": None}
            cloud_model = cloud_resp.model
            if trace is not None:
                trace.provider = "gemini"
                trace.model = cloud_resp.model
            charge(cloud_resp.input_tokens + cloud_resp.output_tokens, f"cloud:{cloud_resp.model}")
        except Exception as e:
            log.error("Cloud dispatch failed: %s — falling back to local", e)
            decision = RoutingDecision(
                route=RouteType.LOCAL, reason="Cloud fallback: provider error",
                confidence=None, pii_detected=prep.pii_result.has_pii,
                query_hash=prep.qhash, timestamp=decision.timestamp,
            )

    if raw is None:
        raw = generate_local(prep.full_prompt, system=prep.system_prompt or None,
                             temperature=_gen_temp, num_predict=_gen_max_tokens)
        if trace is not None:
            trace.provider = "ollama"
            trace.model = INFERENCE_MODEL
        if "error" in raw:
            # T-120b: Cloud safety net — try cloud providers before giving up
            try:
                _safety_router = get_provider_router()
                _safety_cloud = _safety_router._find_cloud_provider()
                if _safety_cloud and not pii_blocked:
                    from core.interface.models import ProviderMessage as _PM
                    _safety_ctx = _get_cloud_context()
                    _safety_prompt = f"{_safety_ctx}\n\n---\nQuery: {prep.effective_query}" if _safety_ctx else prep.effective_query
                    _safety_msgs = []
                    if prep.system_prompt:
                        _safety_msgs.append(_PM(role="system", content=prep.system_prompt))
                    _safety_msgs.append(_PM(role="user", content=_safety_prompt))
                    _safety_result = _safety_router.route(
                        _safety_msgs, provider=_safety_cloud,
                        temperature=_gen_temp, max_tokens=min(_gen_max_tokens, CLOUD_MAX_TOKENS),
                    )
                    if "[INFERENCE ERROR" not in _safety_result.text:
                        raw = {"response": _safety_result.text, "logprobs": None}
                        cloud_model = _safety_result.model
                        if trace is not None:
                            trace.provider = _safety_result.provider
                            trace.model = _safety_result.model
                        log.info("Cloud safety net succeeded via %s", _safety_cloud)
            except Exception as e:
                log.debug("Cloud safety net failed: %s", e)

        if "error" in raw:
            log.error("Inference error: %s", raw["error"])
            return InferenceResponse(
                text=f"[INFERENCE ERROR: {raw['error']}]",
                route=RouteType.LOCAL, model_used=INFERENCE_MODEL,
                confidence=0.0, pii_scrubbed=prep.pii_scrubbed,
            )

    # Populate trace with PII, room restriction, and content class flags
    if trace is not None:
        if prep.pii_scrubbed:
            trace.pii_anonymized = True
        if _room_allowed_providers is not None and _room_provider_sync:
            trace.room_restricted = True
        # Infer content_class from routing signals if not already set
        if not trace.content_class:
            if trace.never_leave_fired or trace.cosine_gate_fired:
                trace.content_class = "NEVER_LEAVE"
            elif prep.pii_result.has_pii:
                trace.content_class = "SENSITIVE"
            else:
                trace.content_class = "SAFE"

    # Use updated decision (may have changed due to fallbacks)
    ctx = prep._replace(decision=decision)
    result = post_process(raw["response"], raw.get("logprobs"), ctx, cloud_model, trace=trace, skip_nli=skip_nli)
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
        routing_trace=trace.to_dict() if trace else None,
    )
    log_interaction_complete(ctx.session["session_id"], ctx.session["started_at"], ctx.qhash, resp)

    try:
        from core.autonomic.events import emit_event
        emit_event("inference", "complete", {
            "route": decision.route.value, "model": effective_model,
            "confidence": result.confidence.score, "query_hash": prep.qhash,
        })
    except Exception as e:
        log.debug("inference complete emit_event suppressed: %s", e)

    return resp


# ---------------------------------------------------------------------------
# Streaming dispatch (stage 6)
# ---------------------------------------------------------------------------

def dispatch_streaming(
    prep: PreparedContext,
    model_override: str | None = None,
    cloud_name: str | None = None,
    trace: RoutingTrace | None = None,
) -> Iterator[dict]:
    """Stream inference (runs inside inference_active guard)."""
    try:
        from core.autonomic.events import emit_event
        emit_event("inference", "start", {"route": prep.decision.route.value, "query_hash": prep.qhash, "stream": True})
    except Exception as e:
        log.debug("stream inference start emit_event suppressed: %s", e)

    accumulated = []
    use_cloud = prep.decision.route == RouteType.CLOUD
    effective_model = model_override or str(get_setting("inference_model"))
    decision = prep.decision

    if use_cloud:
        decision, _ = check_cloud_gate(prep, decision, streamed=True)
        use_cloud = decision.route == RouteType.CLOUD

    # T-037: Provider system streaming (after PII gate, when non-local provider)
    provider_default = str(get_setting("provider_default"))
    pii_blocked = prep.pii_result.has_pii and not prep.pii_scrubbed
    _stream_cloud_ctx_cache: list[str] = []

    def _get_stream_cloud_context() -> str:
        if not _stream_cloud_ctx_cache:
            _stream_cloud_ctx_cache.append(filter_cloud_context(prep.compiled))
        return _stream_cloud_ctx_cache[0]

    # Check room for cloud provider override (must happen before routing gate)
    _room_provider = None
    _room_model = None
    _room_allowed = None
    _room_ref_stream = None
    _forced_local_stream = "force" in (decision.reason or "").lower()
    try:
        from core.rooms.manager import get_room_manager
        room = get_room_manager().get_active_room()
        _room_ref_stream = room
        _room_allowed = room.allowed_providers
        if not model_override and not _forced_local_stream:
            if room.model.model:
                _room_model = room.model.model
            if room.model.provider:
                _room_provider = room.model.provider
    except (ImportError, ValueError):
        pass

    _gen_temp, _gen_max_tokens = resolve_generation_params(_room_ref_stream)
    _global_temp_s = float(get_setting("inference_temperature"))
    _global_max_tokens_s = int(get_setting("inference_max_tokens"))
    if trace is not None:
        if _gen_temp != _global_temp_s:
            trace.room_temperature = _gen_temp
        if _gen_max_tokens != _global_max_tokens_s:
            trace.room_max_tokens = _gen_max_tokens

    # Room with a cloud provider forces cloud route
    if _room_provider and _room_provider != "ollama" and not pii_blocked:
        use_cloud = True
        decision = decision.model_copy(update={"route": RouteType.CLOUD, "reason": f"Room override ({_room_provider})"})

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
            route_kwargs["temperature"] = _gen_temp
            route_kwargs["max_tokens"] = (
                min(_gen_max_tokens, CLOUD_MAX_TOKENS) if use_cloud else _gen_max_tokens
            )

            # Room model/provider override (only when no explicit model_override)
            if not model_override:
                if _room_model:
                    route_kwargs["model"] = _room_model
                if _room_provider and not pii_blocked:
                    target_provider = _room_provider

            if model_override:
                route_kwargs["model"] = model_override
                target_provider = infer_provider_for_model(model_override) or target_provider
            for delta in router.route_stream(msgs, provider=target_provider, allowed_providers=_room_allowed, **route_kwargs):
                accumulated.append(delta)
                yield {"delta": delta, "done": False, "response": None}
                provider_streamed = True

            if provider_streamed:
                use_cloud = False  # prevent legacy cloud path
                actual_provider = getattr(router, "last_routed_provider", None)
                effective_model = route_kwargs.get("model") or actual_provider or cloud_name or provider_default
                if trace is not None:
                    trace.provider = actual_provider or effective_model
                    trace.model = effective_model
                # Charge estimated tokens for streamed cloud calls
                if effective_model != "local":
                    streamed_text = "".join(accumulated)
                    estimated_tokens = int(len(streamed_text.split()) * 1.3) * 2  # rough in+out
                    charge(estimated_tokens, f"cloud:{effective_model}")
        except Exception as e:
            log.error("Provider stream failed: %s — falling back to legacy path", e)

    _legacy_stream_allowed = _room_allowed is None or "gemini" in _room_allowed
    # NEVER_LEAVE: block legacy cloud path even if use_cloud is set
    if use_cloud and not pii_blocked:
        from core.cognition.providers.content_classifier import ContentClassifier
        from core.interface.models import DataTier
        if ContentClassifier().classify(prep.effective_query) == DataTier.NEVER_LEAVE:
            log.warning("NEVER_LEAVE: blocking legacy cloud path")
            if trace is not None:
                trace.never_leave_fired = True
                trace.content_class = "NEVER_LEAVE"
            use_cloud = False
    if use_cloud and _legacy_stream_allowed:
        from core.cognition.cloud import stream_cloud
        try:
            from core.interface.config import CLOUD_MODEL
            effective_model = CLOUD_MODEL
            if trace is not None:
                trace.provider = "gemini"
                trace.model = CLOUD_MODEL
            for delta in stream_cloud(prep.effective_query, _get_stream_cloud_context(), system=prep.system_prompt):
                accumulated.append(delta)
                yield {"delta": delta, "done": False, "response": None}
        except Exception as e:
            log.error("Cloud stream failed: %s — falling back to local", e)
            accumulated = []
            use_cloud = False
            effective_model = INFERENCE_MODEL

    if not use_cloud and not provider_streamed:
        if trace is not None:
            trace.provider = "ollama"
            trace.model = effective_model
        preamble_buf = ""
        preamble_done = False
        _local_stream_error = False
        for chunk in generate_local_stream(prep.full_prompt, system=prep.system_prompt or None, model=effective_model,
                                           temperature=_gen_temp, num_predict=_gen_max_tokens):
            if chunk.get("error"):
                _local_stream_error = True
                break
            accumulated.append(chunk["delta"])
            if not chunk["done"]:
                if not preamble_done:
                    preamble_buf += chunk["delta"]
                    if "}" in preamble_buf:
                        cleaned = strip_json_preamble(preamble_buf)
                        if cleaned != preamble_buf:
                            log.info("Stripped JSON preamble from stream")
                        if cleaned.strip():
                            yield {"delta": cleaned, "done": False, "response": None}
                        preamble_done = True
                    elif len(preamble_buf) > 500 or (preamble_buf.lstrip() and not preamble_buf.lstrip().startswith("{")):
                        yield {"delta": preamble_buf, "done": False, "response": None}
                        preamble_done = True
                else:
                    yield {"delta": chunk["delta"], "done": False, "response": None}

        # T-120b: Cloud safety net for streaming — try cloud if local stream errored
        if _local_stream_error and not pii_blocked:
            try:
                _safety_router = get_provider_router()
                _safety_cloud = _safety_router._find_cloud_provider()
                if _safety_cloud:
                    from core.interface.models import ProviderMessage as _PM
                    _safety_ctx = _get_stream_cloud_context()
                    _safety_prompt = f"{_safety_ctx}\n\n---\nQuery: {prep.effective_query}" if _safety_ctx else prep.effective_query
                    _safety_msgs = []
                    if prep.system_prompt:
                        _safety_msgs.append(_PM(role="system", content=prep.system_prompt))
                    _safety_msgs.append(_PM(role="user", content=_safety_prompt))
                    accumulated = []
                    for delta in _safety_router.route_stream(
                        _safety_msgs, provider=_safety_cloud,
                        temperature=_gen_temp, max_tokens=min(_gen_max_tokens, CLOUD_MAX_TOKENS),
                    ):
                        accumulated.append(delta)
                        yield {"delta": delta, "done": False, "response": None}
                    if trace is not None:
                        trace.provider = _safety_cloud
                        trace.model = "cloud"
                    log.info("Cloud safety net (stream) succeeded via %s", _safety_cloud)
            except Exception as e:
                log.debug("Cloud safety net (stream) failed: %s", e)

    full_text = "".join(accumulated)

    # Populate trace with PII, room restriction, and content class flags
    if trace is not None:
        if prep.pii_scrubbed:
            trace.pii_anonymized = True
        if _room_allowed is not None and _room_provider:
            trace.room_restricted = True
        if not trace.content_class:
            if trace.never_leave_fired or trace.cosine_gate_fired:
                trace.content_class = "NEVER_LEAVE"
            elif prep.pii_result.has_pii:
                trace.content_class = "SENSITIVE"
            else:
                trace.content_class = "SAFE"

    ctx = prep._replace(decision=decision)
    result = post_process(full_text, None, ctx, effective_model, trace=trace)

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
        routing_trace=trace.to_dict() if trace else None,
    )
    log_interaction_complete(ctx.session["session_id"], ctx.session["started_at"], ctx.qhash, resp)

    try:
        from core.autonomic.events import emit_event
        emit_event("inference", "complete", {
            "route": decision.route.value, "model": effective_model,
            "confidence": result.confidence.score, "query_hash": prep.qhash, "stream": True,
        })
    except Exception as e:
        log.debug("stream inference complete emit_event suppressed: %s", e)

    yield {"delta": "", "done": True, "response": resp}
