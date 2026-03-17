"""Tests for handler orchestration."""

from unittest.mock import MagicMock, patch

from core.interface.models import (
    CloudResponse,
    CompiledContext,
    ConfidenceResult,
    ContextSlice,
    MemoryTier,
    PIIEntity,
    PIIResult,
    RoutingDecision,
    RouteType,
)


def _mock_generate(response="Test answer", logprobs=None):
    return {
        "response": response,
        "logprobs": logprobs,
        "eval_count": 10,
        "eval_duration": 500,
    }


def _mock_confidence(score=75.0, method="degraded"):
    return ConfidenceResult(score=score, method=method)


def _mock_pii_clean():
    return PIIResult(has_pii=False, entities=[])


def _mock_pii_dirty():
    return PIIResult(
        has_pii=True,
        entities=[PIIEntity(entity_type="PERSON", text="John", start=5, end=9, score=0.9)],
    )


def _mock_compiled():
    return CompiledContext(
        query="test",
        slices=[
            ContextSlice(name="core", tier=MemoryTier.CORE, fragments=["identity data"], token_count=100, max_tokens=200),
            ContextSlice(name="semantic", tier=MemoryTier.SEMANTIC, fragments=["knowledge"], token_count=100, max_tokens=200),
            ContextSlice(name="episodic", tier=MemoryTier.EPISODIC, fragments=["session log"], token_count=100, max_tokens=200),
        ],
        total_tokens=300,
        budget=6000,
    )


def _mock_scrub():
    return PIIResult(
        has_pii=True,
        entities=[PIIEntity(entity_type="PERSON", text="John", start=5, end=9, score=0.9)],
        scrubbed_text="Tell <PERSON_1> hello",
        anonymization_map={"<PERSON_1>": "John"},
    )


@patch("core.cognition.handler.log_routing_decision")
@patch("core.cognition.handler.route_query")
@patch("core.cognition.handler.score_response", return_value=_mock_confidence())
@patch("core.cognition.handler.generate_local", return_value=_mock_generate())
@patch("core.cognition.handler.load_system_prompt", return_value="system")
@patch("core.cognition.handler.compile_context")
@patch("core.cognition.handler.render_context", return_value="context block")
@patch("core.cognition.handler.detect_pii", return_value=_mock_pii_clean())
def test_execute_query_clean_local(
    mock_detect, mock_render, mock_compile, mock_sys, mock_gen, mock_score, mock_route, mock_log_route
):
    from core.cognition.handler import execute_query

    mock_route.return_value = RoutingDecision(
        route=RouteType.LOCAL, reason="test", confidence=_mock_confidence(),
        pii_detected=False, query_hash="abc", timestamp="2026-01-01",
    )

    resp = execute_query("What is Python?")
    assert resp.text == "Test answer"
    assert resp.route == RouteType.LOCAL
    assert resp.pii_scrubbed is False
    mock_log_route.assert_called_once()


@patch("core.cognition.handler.log_routing_decision")
@patch("core.cognition.handler.route_query")
@patch("core.cognition.handler.score_response", return_value=_mock_confidence())
@patch("core.cognition.handler.generate_local", return_value=_mock_generate())
@patch("core.cognition.handler.load_system_prompt", return_value="")
@patch("core.cognition.handler.compile_context")
@patch("core.cognition.handler.render_context", return_value="ctx")
@patch("core.cognition.handler.scrub_pii", return_value=_mock_scrub())
@patch("core.cognition.handler.log_detection")
@patch("core.cognition.handler.detect_pii", return_value=_mock_pii_dirty())
def test_execute_query_with_pii(
    mock_detect, mock_log_det, mock_scrub, mock_render, mock_compile,
    mock_sys, mock_gen, mock_score, mock_route, mock_log_route
):
    from core.cognition.handler import execute_query

    mock_route.return_value = RoutingDecision(
        route=RouteType.LOCAL, reason="PII", confidence=_mock_confidence(),
        pii_detected=True, query_hash="abc", timestamp="2026-01-01",
    )

    resp = execute_query("Tell John hello")
    assert resp.pii_scrubbed is True
    mock_log_det.assert_called_once()


@patch("core.cognition.handler.log_routing_decision")
@patch("core.cognition.handler.route_query")
@patch("core.cognition.handler.score_response", return_value=_mock_confidence(score=45.0))
@patch("core.cognition.handler.generate_local", return_value=_mock_generate())
@patch("core.cognition.handler.load_system_prompt", return_value="")
@patch("core.cognition.handler.compile_context", return_value=_mock_compiled())
@patch("core.cognition.handler.render_context", return_value="ctx")
@patch("core.cognition.handler.detect_pii", return_value=_mock_pii_clean())
@patch("core.cognition.handler.check_hard_ceiling", return_value=False)
@patch("core.cognition.handler.charge")
def test_execute_query_low_confidence_cloud_dispatch(
    mock_charge, mock_ceiling, mock_detect, mock_render, mock_compile,
    mock_sys, mock_gen, mock_score, mock_route, mock_log_route
):
    from core.cognition.handler import execute_query

    mock_route.return_value = RoutingDecision(
        route=RouteType.CLOUD, reason="low confidence", confidence=_mock_confidence(45.0),
        pii_detected=False, query_hash="abc", timestamp="2026-01-01",
    )

    mock_cloud_resp = CloudResponse(
        text="Cloud answer", model="claude-sonnet", input_tokens=100, output_tokens=50, latency_ms=500,
    )
    with patch("core.cognition.cloud.send_to_cloud", return_value=mock_cloud_resp):
        resp = execute_query("Complex question")

    assert resp.route == RouteType.CLOUD
    assert resp.text == "Cloud answer"


@patch("core.cognition.handler.log_routing_decision")
@patch("core.cognition.handler.score_response", return_value=_mock_confidence())
@patch("core.cognition.handler.generate_local", return_value=_mock_generate())
@patch("core.cognition.handler.load_system_prompt", return_value="")
@patch("core.cognition.handler.compile_context")
@patch("core.cognition.handler.render_context", return_value="ctx")
@patch("core.cognition.handler.detect_pii", return_value=_mock_pii_clean())
def test_execute_query_force_local(
    mock_detect, mock_render, mock_compile, mock_sys, mock_gen, mock_score, mock_log_route
):
    from core.cognition.handler import execute_query

    resp = execute_query("Complex question", force_local=True)
    assert resp.route == RouteType.LOCAL
    assert resp.routing_decision.reason == "Forced local by user flag"


@patch("core.cognition.handler.log_routing_decision")
@patch("core.cognition.handler.route_query")
@patch("core.cognition.handler.score_response", return_value=_mock_confidence())
@patch("core.cognition.handler.generate_local", return_value=_mock_generate())
@patch("core.cognition.handler.load_system_prompt", return_value="")
@patch("core.cognition.handler.compile_context")
@patch("core.cognition.handler.render_context", return_value="ctx")
def test_execute_query_skip_pii(
    mock_render, mock_compile, mock_sys, mock_gen, mock_score, mock_route, mock_log_route
):
    from core.cognition.handler import execute_query

    mock_route.return_value = RoutingDecision(
        route=RouteType.LOCAL, reason="test", confidence=_mock_confidence(),
        pii_detected=False, query_hash="abc", timestamp="2026-01-01",
    )

    resp = execute_query("Tell John hello", skip_pii_scrub=True)
    assert resp.pii_scrubbed is False


@patch("core.cognition.handler.log_routing_decision")
@patch("core.cognition.handler.score_response")
@patch("core.cognition.handler.generate_local", return_value={"error": "Ollama down", "response": ""})
@patch("core.cognition.handler.load_system_prompt", return_value="")
@patch("core.cognition.handler.compile_context")
@patch("core.cognition.handler.render_context", return_value="ctx")
@patch("core.cognition.handler.detect_pii", return_value=_mock_pii_clean())
def test_execute_query_inference_error(
    mock_detect, mock_render, mock_compile, mock_sys, mock_gen, mock_score, mock_log_route
):
    from core.cognition.handler import execute_query

    resp = execute_query("test")
    assert "[INFERENCE ERROR" in resp.text
    assert resp.confidence == 0.0


def _check_handler_health():
    """Moved from core.cognition.handler — only used by this test."""
    import os
    from core.cognition.inference import check_inference_model, check_logprob_support
    from core.safety.credits import load_credits

    inference_ok = check_inference_model()
    logprob_ok = check_logprob_support() if inference_ok else False

    pii_ok = False
    try:
        from core.safety.pii import get_analyzer
        get_analyzer()
        pii_ok = True
    except Exception:
        pass

    credits_bal = load_credits()
    hard_ceiling = credits_bal.monthly_cap * 2.0
    cloud_bridge = bool(os.environ.get("GEMINI_API_KEY"))

    return {
        "inference_model": inference_ok,
        "logprob_support": logprob_ok,
        "pii_engine": pii_ok,
        "credits": credits_bal.model_dump(),
        "cloud_bridge": cloud_bridge,
        "hard_ceiling_remaining": hard_ceiling - credits_bal.used,
    }


@patch("core.safety.credits.load_credits")
@patch("core.cognition.inference.check_logprob_support", return_value=True)
@patch("core.cognition.inference.check_inference_model", return_value=True)
def test_check_handler_health(mock_inf, mock_lp, mock_cred):
    from core.interface.models import CreditBalance

    mock_cred.return_value = CreditBalance(
        monthly_cap=1000, used=50, remaining=950, in_deficit=False, deficit=0, last_reset="2026-02-01",
    )

    with patch("core.safety.pii.get_analyzer"):
        health = _check_handler_health()

    assert health["inference_model"] is True
    assert health["logprob_support"] is True
    assert health["credits"]["used"] == 50
    assert "cloud_bridge" in health
    assert "hard_ceiling_remaining" in health


# ── Cloud dispatch tests (Phase 6a.1) ──────────────────────────────


@patch("core.cognition.handler.log_routing_decision")
@patch("core.cognition.handler.route_query")
@patch("core.cognition.handler.score_response", return_value=_mock_confidence(score=45.0))
@patch("core.cognition.handler.generate_local", return_value=_mock_generate())
@patch("core.cognition.handler.load_system_prompt", return_value="")
@patch("core.cognition.handler.compile_context", return_value=_mock_compiled())
@patch("core.cognition.handler.render_context", return_value="ctx")
@patch("core.cognition.handler.detect_pii", return_value=_mock_pii_clean())
@patch("core.cognition.handler.check_hard_ceiling", return_value=False)
@patch("core.cognition.handler.charge")
def test_cloud_route_dispatches(
    mock_charge, mock_ceiling, mock_detect, mock_render, mock_compile,
    mock_sys, mock_gen, mock_score, mock_route, mock_log_route
):
    from core.cognition.handler import execute_query

    mock_route.return_value = RoutingDecision(
        route=RouteType.CLOUD, reason="low confidence", confidence=_mock_confidence(45.0),
        pii_detected=False, query_hash="abc", timestamp="2026-01-01",
    )

    mock_cloud_resp = CloudResponse(
        text="Cloud answer", model="claude-sonnet", input_tokens=100, output_tokens=50, latency_ms=500,
    )
    with patch("core.cognition.cloud.send_to_cloud", return_value=mock_cloud_resp):
        resp = execute_query("Complex question")

    assert resp.text == "Cloud answer"
    assert resp.route == RouteType.CLOUD
    mock_charge.assert_called_once_with(150, "cloud:claude-sonnet")


@patch("core.cognition.handler.log_routing_decision")
@patch("core.cognition.handler.route_query")
@patch("core.cognition.handler.score_response", return_value=_mock_confidence(score=45.0))
@patch("core.cognition.handler.generate_local", return_value=_mock_generate())
@patch("core.cognition.handler.load_system_prompt", return_value="")
@patch("core.cognition.handler.compile_context", return_value=_mock_compiled())
@patch("core.cognition.handler.render_context", return_value="ctx")
@patch("core.cognition.handler.detect_pii", return_value=_mock_pii_clean())
@patch("core.cognition.handler.check_hard_ceiling", return_value=True)
def test_cloud_route_hard_ceiling_fallback(
    mock_ceiling, mock_detect, mock_render, mock_compile,
    mock_sys, mock_gen, mock_score, mock_route, mock_log_route
):
    from core.cognition.handler import execute_query

    mock_route.return_value = RoutingDecision(
        route=RouteType.CLOUD, reason="low confidence", confidence=_mock_confidence(45.0),
        pii_detected=False, query_hash="abc", timestamp="2026-01-01",
    )

    resp = execute_query("Complex question")
    assert resp.route == RouteType.LOCAL
    assert resp.routing_decision.reason == "Credit hard ceiling pre-flight (fallback)"


@patch("core.cognition.handler.log_routing_decision")
@patch("core.cognition.handler.route_query")
@patch("core.cognition.handler.score_response", return_value=_mock_confidence(score=45.0))
@patch("core.cognition.handler.generate_local", return_value=_mock_generate())
@patch("core.cognition.handler.load_system_prompt", return_value="")
@patch("core.cognition.handler.compile_context", return_value=_mock_compiled())
@patch("core.cognition.handler.render_context", return_value="ctx")
@patch("core.cognition.handler.detect_pii", return_value=_mock_pii_clean())
@patch("core.cognition.handler.check_hard_ceiling", return_value=False)
def test_cloud_route_failure_fallback(
    mock_ceiling, mock_detect, mock_render, mock_compile,
    mock_sys, mock_gen, mock_score, mock_route, mock_log_route
):
    from core.cognition.handler import execute_query

    mock_route.return_value = RoutingDecision(
        route=RouteType.CLOUD, reason="low confidence", confidence=_mock_confidence(45.0),
        pii_detected=False, query_hash="abc", timestamp="2026-01-01",
    )

    with patch("core.cognition.cloud.send_to_cloud", side_effect=Exception("API down")):
        resp = execute_query("Complex question")

    # Falls back to local result
    assert resp.text == "Test answer"
    assert resp.route == RouteType.LOCAL  # route updated to LOCAL on cloud failure


@patch("core.cognition.handler.log_routing_decision")
@patch("core.cognition.handler.route_query")
@patch("core.cognition.handler.score_response", return_value=_mock_confidence(score=45.0))
@patch("core.cognition.handler.generate_local", return_value=_mock_generate())
@patch("core.cognition.handler.load_system_prompt", return_value="")
@patch("core.cognition.handler.compile_context", return_value=_mock_compiled())
@patch("core.cognition.handler.render_context", return_value="ctx")
@patch("core.cognition.handler.scrub_pii", return_value=PIIResult(has_pii=True, entities=[PIIEntity(entity_type="PERSON", text="John", start=0, end=4, score=0.9)], scrubbed_text=None))
@patch("core.cognition.handler.log_detection")
@patch("core.cognition.handler.detect_pii", return_value=_mock_pii_dirty())
@patch("core.cognition.handler.check_hard_ceiling", return_value=False)
def test_pii_hard_gate_aborts_cloud(
    mock_ceiling, mock_detect, mock_log_det, mock_scrub, mock_render, mock_compile,
    mock_sys, mock_gen, mock_score, mock_route, mock_log_route
):
    from core.cognition.handler import execute_query

    mock_route.return_value = RoutingDecision(
        route=RouteType.CLOUD, reason="low confidence", confidence=_mock_confidence(45.0),
        pii_detected=True, query_hash="abc", timestamp="2026-01-01",
    )

    # scrub_pii returns None scrubbed_text → effective_query == query → PII hard gate
    resp = execute_query("Tell John hello")
    assert resp.route == RouteType.LOCAL
    assert "PII hard-gate" in resp.routing_decision.reason


def test_filter_cloud_context_strips_core_episodic():
    from core.cognition.handler import _filter_cloud_context

    compiled = _mock_compiled()
    with patch("core.cognition.handler.render_context") as mock_render:
        mock_render.return_value = "filtered"
        result = _filter_cloud_context(compiled)

    # Should only pass semantic slice (not core or episodic)
    call_args = mock_render.call_args[0][0]
    assert len(call_args.slices) == 1
    assert call_args.slices[0].name == "semantic"


@patch("core.cognition.handler.log_routing_decision")
@patch("core.cognition.handler.route_query")
@patch("core.cognition.handler.score_response", return_value=_mock_confidence(score=45.0))
@patch("core.cognition.handler.generate_local", return_value=_mock_generate())
@patch("core.cognition.handler.load_system_prompt", return_value="")
@patch("core.cognition.handler.compile_context", return_value=_mock_compiled())
@patch("core.cognition.handler.render_context", return_value="ctx")
@patch("core.cognition.handler.detect_pii", return_value=_mock_pii_clean())
@patch("core.cognition.handler.check_hard_ceiling", return_value=False)
@patch("core.cognition.handler.charge")
def test_cloud_route_charges_credits(
    mock_charge, mock_ceiling, mock_detect, mock_render, mock_compile,
    mock_sys, mock_gen, mock_score, mock_route, mock_log_route
):
    from core.cognition.handler import execute_query

    mock_route.return_value = RoutingDecision(
        route=RouteType.CLOUD, reason="low confidence", confidence=_mock_confidence(45.0),
        pii_detected=False, query_hash="abc", timestamp="2026-01-01",
    )

    mock_cloud_resp = CloudResponse(
        text="Cloud answer", model="claude-sonnet", input_tokens=200, output_tokens=100, latency_ms=300,
    )
    with patch("core.cognition.cloud.send_to_cloud", return_value=mock_cloud_resp):
        execute_query("Complex question")

    mock_charge.assert_called_once_with(300, "cloud:claude-sonnet")


# ── NLI contradiction tests (Phase 6a.3) ────────────────────────────

from core.interface.models import ContradictionResult


def _mock_identity_contradiction():
    return ContradictionResult(
        has_contradiction=True,
        contradiction_type="identity",
        confidence=85.0,
        explanation="Age mismatch",
    )


def _mock_knowledge_contradiction():
    return ContradictionResult(
        has_contradiction=True,
        contradiction_type="knowledge",
        confidence=75.0,
        explanation="Model mismatch",
    )


@patch("core.cognition.handler.log_routing_decision")
@patch("core.cognition.handler.route_query")
@patch("core.cognition.handler.score_response", return_value=_mock_confidence())
@patch("core.cognition.handler.generate_local", return_value=_mock_generate())
@patch("core.cognition.handler.load_system_prompt", return_value="")
@patch("core.cognition.handler.compile_context", return_value=_mock_compiled())
@patch("core.cognition.handler.render_context", return_value="ctx")
@patch("core.cognition.handler.detect_pii", return_value=_mock_pii_clean())
def test_handler_nli_veto(
    mock_detect, mock_render, mock_compile, mock_sys, mock_gen, mock_score, mock_route, mock_log_route
):
    """Cosine gate + identity contradiction -> veto response."""
    from core.cognition.handler import execute_query

    mock_route.return_value = RoutingDecision(
        route=RouteType.LOCAL, reason="Cosine gate", confidence=_mock_confidence(),
        pii_detected=False, query_hash="abc", timestamp="2026-01-01",
        cosine_gate_fired=True,
    )

    with (
        patch("core.memory.search.hybrid_search", return_value=[]),
        patch("core.identity.contradiction.check_contradiction", return_value=_mock_identity_contradiction()),
    ):
        resp = execute_query("Who is the Architect?")

    assert "[HARD VETO]" in resp.text
    assert resp.confidence == 0.0
    assert resp.contradiction is not None
    assert resp.contradiction.contradiction_type == "identity"


@patch("core.cognition.handler.log_routing_decision")
@patch("core.cognition.handler.route_query")
@patch("core.cognition.handler.score_response", return_value=_mock_confidence(score=70.0))
@patch("core.cognition.handler.generate_local", return_value=_mock_generate())
@patch("core.cognition.handler.load_system_prompt", return_value="")
@patch("core.cognition.handler.compile_context", return_value=_mock_compiled())
@patch("core.cognition.handler.render_context", return_value="ctx")
@patch("core.cognition.handler.detect_pii", return_value=_mock_pii_clean())
def test_handler_nli_penalty(
    mock_detect, mock_render, mock_compile, mock_sys, mock_gen, mock_score, mock_route, mock_log_route
):
    """Cosine gate + knowledge contradiction -> confidence penalty."""
    from core.cognition.handler import execute_query

    mock_route.return_value = RoutingDecision(
        route=RouteType.LOCAL, reason="Cosine gate", confidence=_mock_confidence(70.0),
        pii_detected=False, query_hash="abc", timestamp="2026-01-01",
        cosine_gate_fired=True,
    )

    with (
        patch("core.memory.search.hybrid_search", return_value=[]),
        patch("core.identity.contradiction.check_contradiction", return_value=_mock_knowledge_contradiction()),
    ):
        resp = execute_query("What stack do we use?")

    assert resp.confidence == 50.0  # 70 - 20 penalty
    assert resp.contradiction is not None


@patch("core.cognition.handler.log_routing_decision")
@patch("core.cognition.handler.route_query")
@patch("core.cognition.handler.score_response", return_value=_mock_confidence())
@patch("core.cognition.handler.generate_local", return_value=_mock_generate())
@patch("core.cognition.handler.load_system_prompt", return_value="")
@patch("core.cognition.handler.compile_context", return_value=_mock_compiled())
@patch("core.cognition.handler.render_context", return_value="ctx")
@patch("core.cognition.handler.detect_pii", return_value=_mock_pii_clean())
def test_handler_nli_skipped_non_sovereign(
    mock_detect, mock_render, mock_compile, mock_sys, mock_gen, mock_score, mock_route, mock_log_route
):
    """No cosine gate -> no NLI call."""
    from core.cognition.handler import execute_query

    mock_route.return_value = RoutingDecision(
        route=RouteType.LOCAL, reason="High confidence", confidence=_mock_confidence(),
        pii_detected=False, query_hash="abc", timestamp="2026-01-01",
        cosine_gate_fired=False,
    )

    with patch("core.identity.contradiction.check_contradiction") as mock_nli:
        resp = execute_query("What is Python?")

    mock_nli.assert_not_called()
    assert resp.contradiction is None


# ── Streaming NLI tests (Phase 6a.3 — stream path) ──────────────


def _mock_local_stream_chunks(text="Streamed answer"):
    """Generate mock stream chunks for generate_local_stream."""
    for ch in text:
        yield {"delta": ch, "done": False}
    yield {"delta": "", "done": True}


@patch("core.cognition.handler.log_routing_decision")
@patch("core.cognition.handler.route_query")
@patch("core.cognition.handler.score_response", return_value=_mock_confidence())
@patch("core.cognition.handler.load_system_prompt", return_value="")
@patch("core.cognition.handler.compile_context", return_value=_mock_compiled())
@patch("core.cognition.handler.render_context", return_value="ctx")
@patch("core.cognition.handler.detect_pii", return_value=_mock_pii_clean())
def test_stream_nli_identity_veto_appends_warning(
    mock_detect, mock_render, mock_compile, mock_sys, mock_score, mock_route, mock_log_route
):
    """Streaming + cosine gate + identity contradiction -> warning appended to stream."""
    from core.cognition.handler import execute_query_stream

    mock_route.return_value = RoutingDecision(
        route=RouteType.LOCAL, reason="Cosine gate", confidence=_mock_confidence(),
        pii_detected=False, query_hash="abc", timestamp="2026-01-01",
        cosine_gate_fired=True,
    )

    with (
        patch("core.cognition.handler.generate_local_stream", return_value=_mock_local_stream_chunks()),
        patch("core.memory.search.hybrid_search", return_value=[]),
        patch("core.identity.contradiction.check_contradiction", return_value=_mock_identity_contradiction()),
    ):
        chunks = list(execute_query_stream("Who is the Architect?"))

    # Final chunk should be done=True with response
    final = chunks[-1]
    assert final["done"] is True
    resp = final["response"]
    assert resp.confidence == 0.0
    assert resp.contradiction is not None
    assert resp.contradiction.contradiction_type == "identity"
    # Warning delta should have been yielded before final
    deltas = [c["delta"] for c in chunks if not c["done"]]
    full_text = "".join(deltas)
    assert "IDENTITY CONTRADICTION" in full_text


@patch("core.cognition.handler.log_routing_decision")
@patch("core.cognition.handler.route_query")
@patch("core.cognition.handler.score_response", return_value=_mock_confidence(score=70.0))
@patch("core.cognition.handler.load_system_prompt", return_value="")
@patch("core.cognition.handler.compile_context", return_value=_mock_compiled())
@patch("core.cognition.handler.render_context", return_value="ctx")
@patch("core.cognition.handler.detect_pii", return_value=_mock_pii_clean())
def test_stream_nli_knowledge_penalty(
    mock_detect, mock_render, mock_compile, mock_sys, mock_score, mock_route, mock_log_route
):
    """Streaming + cosine gate + knowledge contradiction -> confidence penalty."""
    from core.cognition.handler import execute_query_stream

    mock_route.return_value = RoutingDecision(
        route=RouteType.LOCAL, reason="Cosine gate", confidence=_mock_confidence(70.0),
        pii_detected=False, query_hash="abc", timestamp="2026-01-01",
        cosine_gate_fired=True,
    )

    with (
        patch("core.cognition.handler.generate_local_stream", return_value=_mock_local_stream_chunks()),
        patch("core.memory.search.hybrid_search", return_value=[]),
        patch("core.identity.contradiction.check_contradiction", return_value=_mock_knowledge_contradiction()),
    ):
        chunks = list(execute_query_stream("What stack do we use?"))

    final = chunks[-1]
    assert final["done"] is True
    resp = final["response"]
    assert resp.confidence == 50.0  # 70 - 20 penalty
    assert resp.contradiction is not None


@patch("core.cognition.handler.log_routing_decision")
@patch("core.cognition.handler.route_query")
@patch("core.cognition.handler.score_response", return_value=_mock_confidence())
@patch("core.cognition.handler.load_system_prompt", return_value="")
@patch("core.cognition.handler.compile_context", return_value=_mock_compiled())
@patch("core.cognition.handler.render_context", return_value="ctx")
@patch("core.cognition.handler.detect_pii", return_value=_mock_pii_clean())
def test_stream_nli_mission_keyword_trigger(
    mock_detect, mock_render, mock_compile, mock_sys, mock_score, mock_route, mock_log_route
):
    """Mission keyword in query triggers NLI even without cosine gate."""
    from core.cognition.handler import execute_query_stream

    mock_route.return_value = RoutingDecision(
        route=RouteType.LOCAL, reason="High confidence", confidence=_mock_confidence(),
        pii_detected=False, query_hash="abc", timestamp="2026-01-01",
        cosine_gate_fired=False,
    )

    mock_nli = MagicMock(return_value=ContradictionResult(
        has_contradiction=False, contradiction_type="none", confidence=0.0, explanation="",
    ))

    with (
        patch("core.cognition.handler.generate_local_stream", return_value=_mock_local_stream_chunks()),
        patch("core.memory.search.hybrid_search", return_value=[]),
        patch("core.identity.contradiction.check_contradiction", mock_nli),
    ):
        chunks = list(execute_query_stream("Should I give up on music for a day job?"))

    mock_nli.assert_called_once()  # NLI fired due to "give up" + "day job"


# ── _prepare_query / _post_process unit tests ────────────────────


@patch("core.cognition.handler.log_interaction")
@patch("core.cognition.handler.get_or_create_session", return_value={"session_id": "s1", "started_at": "t0"})
@patch("core.cognition.handler.route_query")
@patch("core.cognition.handler.load_system_prompt", return_value="system")
@patch("core.cognition.handler.compile_context")
@patch("core.cognition.handler.render_context", return_value="context block")
@patch("core.cognition.handler.detect_pii", return_value=_mock_pii_clean())
@patch("core.cognition.handler.detect_adversarial")
def test_prepare_query_returns_prepared_context(
    mock_adv, mock_detect, mock_render, mock_compile, mock_sys, mock_route, mock_session, mock_log_int
):
    from core.cognition.handler import _prepare_query, PreparedContext
    from core.identity.input_guard import AdversarialResult

    mock_adv.return_value = AdversarialResult(is_adversarial=False, severity=0, matched_patterns=[])
    mock_route.return_value = RoutingDecision(
        route=RouteType.LOCAL, reason="test", confidence=_mock_confidence(),
        pii_detected=False, query_hash="abc", timestamp="2026-01-01",
    )

    result = _prepare_query("What is Python?")
    assert isinstance(result, PreparedContext)
    assert result.effective_query == "What is Python?"
    assert result.pii_scrubbed is False
    assert result.decision.route == RouteType.LOCAL
    assert result.system_prompt == "system"
    assert result.qhash is not None
    assert result.session == {"session_id": "s1", "started_at": "t0"}


@patch("core.cognition.handler.score_response", return_value=_mock_confidence(score=80.0))
def test_post_process_applies_checks_in_order(mock_score):
    from core.cognition.handler import _post_process, PreparedContext, PostProcessResult

    ctx = PreparedContext(
        decision=RoutingDecision(
            route=RouteType.LOCAL, reason="test", confidence=_mock_confidence(),
            pii_detected=False, query_hash="abc", timestamp="2026-01-01",
            cosine_gate_fired=False,
        ),
        pii_result=_mock_pii_clean(),
        effective_query="What is Python?",
        pii_scrubbed=False,
        compiled=_mock_compiled(),
        context_block="ctx",
        system_prompt="system",
        full_prompt="ctx\n\n---\nQuery: What is Python?",
        session={"session_id": "s1", "started_at": "t0"},
        qhash="abc",
    )

    result = _post_process("Test answer", None, ctx, "qwen2.5:14b")
    assert isinstance(result, PostProcessResult)
    assert result.confidence.score == 80.0
    assert result.contradiction is None
    assert result.is_hard_veto is False
    assert isinstance(result.warnings, list)


# ── JSON preamble stripping ─────────────────────────────────────────


def test_strip_json_preamble_removes_classifier_json():
    from core.cognition.handler import _strip_json_preamble

    text = '{"contains_assertion": false, "assertion_type": "none", "extracted_claim": null} The Architect is RULEZ.'
    assert _strip_json_preamble(text) == "The Architect is RULEZ."


def test_strip_json_preamble_preserves_clean_text():
    from core.cognition.handler import _strip_json_preamble

    text = "Standing by. The Void is watching."
    assert _strip_json_preamble(text) == text


def test_strip_json_preamble_preserves_non_classifier_json():
    from core.cognition.handler import _strip_json_preamble

    text = '{"key": "value"} some text'
    assert _strip_json_preamble(text) == text


def test_strip_json_preamble_handles_whitespace():
    from core.cognition.handler import _strip_json_preamble

    text = '  \n{"contains_assertion": true, "assertion_type": "location", "extracted_claim": "I moved to LA"}  \nActual response here.'
    assert _strip_json_preamble(text).strip() == "Actual response here."


def test_strip_json_preamble_does_not_empty_response():
    from core.cognition.handler import _strip_json_preamble

    text = '{"contains_assertion": false, "assertion_type": "none", "extracted_claim": null}'
    result = _strip_json_preamble(text)
    assert result == text  # Preserve if stripping would leave empty


@patch("core.cognition.handler.score_response")
def test_post_process_strips_json_preamble(mock_score):
    mock_score.return_value = ConfidenceResult(score=80.0, method="degraded")
    from core.cognition.handler import _post_process, PreparedContext

    ctx = PreparedContext(
        decision=RoutingDecision(
            route=RouteType.LOCAL, reason="test", confidence=_mock_confidence(),
            pii_detected=False, query_hash="abc", timestamp="2026-01-01",
            cosine_gate_fired=False,
        ),
        pii_result=_mock_pii_clean(),
        effective_query="test",
        pii_scrubbed=False,
        compiled=_mock_compiled(),
        context_block="ctx",
        system_prompt="system",
        full_prompt="ctx\n\n---\nQuery: test",
        session={"session_id": "s1", "started_at": "t0"},
        qhash="abc",
    )

    result = _post_process(
        '{"contains_assertion": false, "assertion_type": "none", "extracted_claim": null} Clean response.',
        None, ctx, "qwen2.5:14b",
    )
    assert "contains_assertion" not in result.text
    assert "Clean response." in result.text


def test_strip_json_preamble_removes_coherence_json():
    from core.cognition.handler import _strip_json_preamble

    text = '{"is_coherent": true, "score": 0.95} The Void is watching. Standing by.'
    result = _strip_json_preamble(text)
    assert "is_coherent" not in result
    assert "The Void is watching. Standing by." in result


@patch("core.cognition.handler.score_response")
def test_post_process_strips_coherence_json_second_pass(mock_score):
    mock_score.return_value = ConfidenceResult(score=80.0, method="degraded")
    from core.cognition.handler import _post_process, PreparedContext

    ctx = PreparedContext(
        decision=RoutingDecision(
            route=RouteType.LOCAL, reason="test", confidence=_mock_confidence(),
            pii_detected=False, query_hash="abc", timestamp="2026-01-01",
            cosine_gate_fired=False,
        ),
        pii_result=_mock_pii_clean(),
        effective_query="test",
        pii_scrubbed=False,
        compiled=_mock_compiled(),
        context_block="ctx",
        system_prompt="system",
        full_prompt="ctx\n\n---\nQuery: test",
        session={"session_id": "s1", "started_at": "t0"},
        qhash="abc",
    )

    result = _post_process(
        '{"is_coherent": true, "score": 0.95} The system is operational.',
        None, ctx, "qwen2.5:14b",
    )
    assert "is_coherent" not in result.text
    assert "The system is operational." in result.text


# ── Model override validation ───────────────────────────────────────


@patch("core.cognition.handler._prepare_query")
@patch("core.cognition.inference.validate_model_name", return_value="Model 'fake:7b' not found. Available: qwen2.5:14b")
def test_model_override_invalid_returns_error(mock_validate, mock_prep):
    from core.cognition.handler import execute_query_stream
    chunks = list(execute_query_stream("test", model_override="fake:7b"))
    assert any("[MODEL ERROR]" in c.get("delta", "") for c in chunks)
    assert chunks[-1]["done"] is True
    mock_prep.assert_not_called()  # should short-circuit before prepare
