"""Tests for trace population across pipeline stages."""

from unittest.mock import patch, MagicMock
from datetime import datetime, timezone

from core.cognition.pipeline.trace import RoutingTrace
from core.interface.models import (
    CompiledContext, ConfidenceResult, PIIResult,
    RoutingDecision, RouteType,
)
from core.cognition.pipeline import PreparedContext


def test_classify_returns_result():
    """classify_input returns ClassifyResult on benign input."""
    with patch("core.cognition.pipeline.classify.detect_adversarial") as mock_adv:
        mock_adv.return_value = MagicMock(is_adversarial=False, severity=0, matched_patterns=[])
        from core.cognition.pipeline.classify import classify_input, ClassifyResult
        result = classify_input("What is the weather?", "hash123")
    assert isinstance(result, ClassifyResult)


def test_route_force_local_accepts_trace():
    """make_routing_decision with force_local accepts trace without error."""
    trace = RoutingTrace()
    from core.cognition.pipeline.route import make_routing_decision
    decision = make_routing_decision(
        "hello", PIIResult(has_pii=False, entities=[]),
        "abc123", force_local=True, trace=trace,
    )
    assert decision.route == RouteType.LOCAL


def test_route_cosine_gate_populates_trace():
    """When cosine gate fires in route_query, trace.cosine_gate_fired is set."""
    trace = RoutingTrace()
    with patch("core.cognition.complexity.score_complexity", return_value={"penalty": 50}), \
         patch("core.memory.embedder.embed_single", return_value=[0.1] * 768), \
         patch("core.safety.sensitivity.check_sovereign_similarity", return_value=True):
        from core.cognition.pipeline.route import make_routing_decision
        decision = make_routing_decision(
            "who am I", PIIResult(has_pii=False, entities=[]),
            "abc456", trace=trace,
        )
    assert decision.cosine_gate_fired
    assert trace.cosine_gate_fired


def test_route_moderate_complexity_populates_trace():
    """When complexity penalty is 50-99, trace.complexity is MODERATE."""
    trace = RoutingTrace()
    mock_decision = MagicMock()
    mock_decision.cosine_gate_fired = False
    mock_decision.route = RouteType.LOCAL
    with patch("core.cognition.complexity.score_complexity", return_value={"penalty": 60}), \
         patch("core.memory.embedder.embed_single", side_effect=RuntimeError), \
         patch("core.cognition.routing.route_query", return_value=mock_decision):
        from core.cognition.pipeline.route import make_routing_decision
        make_routing_decision(
            "complex question", PIIResult(has_pii=False, entities=[]),
            "abc789", trace=trace,
        )
    assert trace.complexity == "MODERATE"


def test_postprocess_output_filter_populates_trace():
    """postprocess sets output_filtered when filter fires."""
    trace = RoutingTrace()
    prep = PreparedContext(
        decision=RoutingDecision(
            route=RouteType.LOCAL, reason="test (no NLI)",
            confidence=None, pii_detected=False,
            query_hash="test123",
            timestamp=datetime.now(timezone.utc).isoformat(),
        ),
        pii_result=PIIResult(has_pii=False, entities=[]),
        effective_query="test query",
        pii_scrubbed=False,
        compiled=CompiledContext(query="test", slices=[], total_tokens=0, budget=4000),
        context_block="",
        system_prompt=None,
        full_prompt="test query",
        session={"session_id": "test-session", "started_at": "2026-01-01"},
        qhash="abc123",
    )
    with patch("core.cognition.pipeline.postprocess.score_response") as mock_score:
        mock_score.return_value = ConfidenceResult(score=85.0, method="logprob")
        with patch("core.safety.output_filter.check_output_sensitivity") as mock_filter:
            mock_filter.return_value = MagicMock(
                response="[REDACTED]", level="CRITICAL", triggered=["credential_pattern"],
            )
            from core.cognition.pipeline.postprocess import post_process
            post_process("sk-ant-api03-secret", None, prep, "qwen2.5:14b", trace=trace)
    assert trace.output_filtered
