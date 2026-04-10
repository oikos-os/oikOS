"""Handler orchestration — wires PII, routing, inference, credits, response."""

from __future__ import annotations

import logging

from typing import Iterator

from core.interface.config import INFERENCE_MODEL
from core.interface.models import (
    DataTier,
    InferenceResponse,
    RoutingDecision,
    RouteType,
)
from core.cognition.pipeline import PreparedContext
from core.cognition.pipeline.classify import classify_input
from core.cognition.pipeline.dispatch import (
    dispatch_blocking,
    dispatch_streaming,
    infer_provider_for_model,
)
from core.cognition.pipeline.trace import RoutingTrace
from core.cognition.routing import query_hash
from core.memory.session import get_or_create_session, log_interaction

log = logging.getLogger(__name__)


def _prepare_query(
    query: str,
    force_local: bool = False,
    force_cloud: bool = False,
    skip_pii_scrub: bool = False,
    source: str = "handler",
) -> tuple[PreparedContext, RoutingTrace] | InferenceResponse:
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
    trace = RoutingTrace()

    # 0. Session tracking
    session = get_or_create_session()
    log_interaction(session["session_id"], session["started_at"], qhash, query, source=source)

    # 0b. FSM auto-transition (non-blocking)
    try:
        from core.autonomic.fsm import get_current_state, transition_to
        from core.interface.models import SystemState
        if get_current_state() in (SystemState.IDLE, SystemState.ASLEEP):
            transition_to(SystemState.ACTIVE, trigger="auto:query")
    except Exception as e:
        log.debug("FSM auto-transition suppressed: %s", e)

    classify_result = classify_input(query, qhash, skip_pii_scrub)
    if isinstance(classify_result, InferenceResponse):
        return classify_result
    effective_query = classify_result.effective_query
    pii_result = classify_result.pii_result
    pii_scrubbed = classify_result.pii_scrubbed

    from core.cognition.pipeline.context import assemble_context
    ctx_result = assemble_context(effective_query)
    compiled = ctx_result.compiled
    context_block = ctx_result.context_block
    system_prompt = ctx_result.system_prompt
    full_prompt = ctx_result.full_prompt

    # 4b–5. Complexity pre-score + route decision
    from core.cognition.pipeline.route import make_routing_decision
    decision = make_routing_decision(effective_query, pii_result, qhash, force_local=force_local, force_cloud=force_cloud, trace=trace)

    return (
        PreparedContext(
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
        ),
        trace,
    )


def execute_query(
    query: str,
    force_local: bool = False,
    force_cloud: bool = False,
    skip_pii_scrub: bool = False,
    cloud_name: str | None = None,
    model_override: str | None = None,
    skip_nli: bool = False,
) -> InferenceResponse:
    """Full query pipeline: session -> PII -> context -> inference -> confidence -> routing -> response."""
    result = _prepare_query(query, force_local, force_cloud, skip_pii_scrub, source="handler")
    if isinstance(result, InferenceResponse):
        return result
    prep, trace = result

    from core.autonomic.daemon import inference_active

    with inference_active():
        return dispatch_blocking(prep, model_override=model_override, cloud_name=cloud_name, trace=trace, skip_nli=skip_nli)


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

    result = _prepare_query(query, force_local, force_cloud, skip_pii_scrub, source="stream")
    if isinstance(result, InferenceResponse):
        yield {"delta": result.text, "done": False, "response": None}
        yield {"delta": "", "done": True, "response": result}
        return
    prep, trace = result

    from core.autonomic.daemon import inference_active

    # Apply model override: if it matches a cloud model, force cloud route
    # NEVER_LEAVE check: classify user input before allowing cloud override
    if model_override:
        from core.interface.config import CLOUD_MODEL
        if model_override == CLOUD_MODEL or model_override.startswith("claude-"):
            from core.cognition.providers.content_classifier import ContentClassifier
            _tier = ContentClassifier().classify(query)
            trace.content_class = _tier.value
            if _tier == DataTier.NEVER_LEAVE:
                log.warning("NEVER_LEAVE: blocking cloud model override '%s' — forcing local", model_override)
                trace.never_leave_fired = True
                model_override = None  # clear override, stay local
            else:
                prep = prep._replace(
                    decision=RoutingDecision(
                        route=RouteType.CLOUD, reason="Model override (cloud)",
                        confidence=None, pii_detected=prep.pii_result.has_pii,
                        query_hash=prep.qhash, timestamp=prep.decision.timestamp,
                    ),
                )

    with inference_active():
        yield from dispatch_streaming(prep, model_override=model_override, cloud_name=cloud_name, trace=trace)
