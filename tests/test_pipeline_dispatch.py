"""Tests for core.cognition.pipeline.dispatch — inference dispatch paths."""

from unittest.mock import MagicMock, patch

from core.interface.models import (
    CompiledContext,
    ConfidenceResult,
    ContextSlice,
    MemoryTier,
    PIIEntity,
    PIIResult,
    RoutingDecision,
    RouteType,
)
from core.cognition.pipeline import PreparedContext


def _confidence(score=75.0):
    return ConfidenceResult(score=score, method="degraded")


def _pii_clean():
    return PIIResult(has_pii=False, entities=[])


def _pii_dirty_unscrubbed():
    return PIIResult(
        has_pii=True,
        entities=[PIIEntity(entity_type="PERSON", text="John", start=0, end=4, score=0.9)],
    )


def _compiled():
    return CompiledContext(
        query="test",
        slices=[
            ContextSlice(name="core", tier=MemoryTier.CORE, fragments=["id"], token_count=50, max_tokens=200),
            ContextSlice(name="semantic", tier=MemoryTier.SEMANTIC, fragments=["kb"], token_count=50, max_tokens=200),
        ],
        total_tokens=100,
        budget=6000,
    )


def _prep(pii_result=None, route=RouteType.LOCAL, reason="test", pii_scrubbed=False):
    return PreparedContext(
        decision=RoutingDecision(
            route=route, reason=reason, confidence=_confidence(),
            pii_detected=(pii_result or _pii_clean()).has_pii,
            query_hash="abc123", timestamp="2026-01-01",
        ),
        pii_result=pii_result or _pii_clean(),
        effective_query="What is Python?",
        pii_scrubbed=pii_scrubbed,
        compiled=_compiled(),
        context_block="ctx",
        system_prompt="system",
        full_prompt="ctx\n\n---\nQuery: What is Python?",
        session={"session_id": "s1", "started_at": "t0"},
        qhash="abc123",
    )


# ── check_cloud_gate tests ────────────────────────────────────────


def test_cloud_gate_pii_blocks():
    """Unscrubbed PII on cloud route → LOCAL downgrade."""
    from core.cognition.pipeline.dispatch import check_cloud_gate

    prep = _prep(pii_result=_pii_dirty_unscrubbed(), route=RouteType.CLOUD, pii_scrubbed=False)
    decision, pii_blocked = check_cloud_gate(prep, prep.decision)

    assert decision.route == RouteType.LOCAL
    assert "PII hard-gate" in decision.reason
    assert pii_blocked is True


@patch("core.cognition.pipeline.dispatch.check_hard_ceiling", return_value=False)
def test_cloud_gate_passes_when_clean(mock_ceiling):
    """No PII, ceiling OK → cloud allowed."""
    from core.cognition.pipeline.dispatch import check_cloud_gate

    prep = _prep(route=RouteType.CLOUD)
    decision, pii_blocked = check_cloud_gate(prep, prep.decision)

    assert decision.route == RouteType.CLOUD
    assert pii_blocked is False


# ── dispatch_blocking tests ───────────────────────────────────────


@patch("core.cognition.pipeline.dispatch.log_routing_decision")
@patch("core.cognition.pipeline.dispatch.log_interaction_complete")
@patch("core.cognition.pipeline.postprocess.score_response", return_value=_confidence())
@patch("core.cognition.pipeline.dispatch.generate_local", return_value={
    "response": "Local answer", "logprobs": None, "eval_count": 10, "eval_duration": 500,
})
@patch("core.cognition.pipeline.dispatch.get_setting", side_effect=lambda k: {
    "provider_default": "local", "inference_model": "qwen2.5:14b",
    "inference_temperature": 0.7, "inference_max_tokens": 2048,
}.get(k, "local"))
def test_local_dispatch_happy_path(mock_setting, mock_gen, mock_score, mock_log_complete, mock_log_route):
    """Local dispatch returns response from generate_local."""
    from core.cognition.pipeline.dispatch import dispatch_blocking

    prep = _prep()
    resp = dispatch_blocking(prep)

    assert resp.text == "Local answer"
    assert resp.route == RouteType.LOCAL
    assert resp.confidence == 75.0
    mock_gen.assert_called_once()
    mock_log_route.assert_called_once()


@patch("core.cognition.pipeline.dispatch.log_routing_decision")
@patch("core.cognition.pipeline.dispatch.log_interaction_complete")
@patch("core.cognition.pipeline.dispatch.get_provider_router")
@patch("core.cognition.pipeline.dispatch.generate_local", return_value={"error": "Ollama down", "response": ""})
@patch("core.cognition.pipeline.dispatch.get_setting", side_effect=lambda k: {
    "provider_default": "local", "inference_model": "qwen2.5:14b",
    "inference_temperature": 0.7, "inference_max_tokens": 2048,
}.get(k, "local"))
def test_local_dispatch_inference_error_no_cloud(mock_setting, mock_gen, mock_router, mock_log_complete, mock_log_route):
    """generate_local error with no cloud provider returns INFERENCE ERROR."""
    from core.cognition.pipeline.dispatch import dispatch_blocking

    mock_router.return_value._find_cloud_provider.return_value = None
    prep = _prep()
    resp = dispatch_blocking(prep)

    assert "[INFERENCE ERROR" in resp.text
    assert resp.confidence == 0.0
    assert resp.route == RouteType.LOCAL


# ── T-120b: Cloud safety net tests ──────────────────────────────────


@patch("core.cognition.pipeline.dispatch.log_routing_decision")
@patch("core.cognition.pipeline.dispatch.log_interaction_complete")
@patch("core.cognition.pipeline.postprocess.score_response", return_value=_confidence())
@patch("core.cognition.pipeline.dispatch.get_provider_router")
@patch("core.cognition.pipeline.dispatch.generate_local", return_value={"error": "Ollama down", "response": ""})
@patch("core.cognition.pipeline.dispatch.get_setting", side_effect=lambda k: {
    "provider_default": "local", "inference_model": "qwen2.5:14b",
    "inference_temperature": 0.7, "inference_max_tokens": 2048,
}.get(k, "local"))
def test_cloud_safety_net_fires_on_local_error(mock_setting, mock_gen, mock_router, mock_score, mock_log_complete, mock_log_route):
    """T-120b: When generate_local errors, cloud safety net routes to cloud."""
    from core.cognition.pipeline.dispatch import dispatch_blocking
    from core.interface.models import CompletionResponse

    cloud_result = CompletionResponse(
        text="Cloud fallback answer", model="gemini-2.5-pro", provider="gemini",
    )
    mock_router.return_value._find_cloud_provider.return_value = "gemini"
    mock_router.return_value.route.return_value = cloud_result

    prep = _prep()
    resp = dispatch_blocking(prep)

    assert resp.text == "Cloud fallback answer"
    mock_router.return_value.route.assert_called_once()


@patch("core.cognition.pipeline.dispatch.log_routing_decision")
@patch("core.cognition.pipeline.dispatch.log_interaction_complete")
@patch("core.cognition.pipeline.dispatch.get_provider_router")
@patch("core.cognition.pipeline.dispatch.generate_local", return_value={"error": "Ollama down", "response": ""})
@patch("core.cognition.pipeline.dispatch.get_setting", side_effect=lambda k: {
    "provider_default": "local", "inference_model": "qwen2.5:14b",
    "inference_temperature": 0.7, "inference_max_tokens": 2048,
}.get(k, "local"))
def test_cloud_safety_net_pii_blocked(mock_setting, mock_gen, mock_router, mock_log_complete, mock_log_route):
    """T-120b: Cloud safety net does NOT fire when PII is unscrubbed."""
    from core.cognition.pipeline.dispatch import dispatch_blocking

    mock_router.return_value._find_cloud_provider.return_value = "gemini"

    prep = _prep(pii_result=_pii_dirty_unscrubbed())
    resp = dispatch_blocking(prep)

    assert "[INFERENCE ERROR" in resp.text
    mock_router.return_value.route.assert_not_called()
