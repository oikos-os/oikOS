"""Tests for pipeline/postprocess.py — post-inference processing stages."""

from unittest.mock import patch, MagicMock
import pytest

from core.cognition.pipeline import PreparedContext, PostProcessResult
from core.cognition.pipeline.postprocess import post_process
from core.interface.models import (
    CompiledContext, ConfidenceResult, PIIResult, RoutingDecision, RouteType,
)
from datetime import datetime, timezone


def _make_prep(reason="Force-local test", cosine_gate_fired=False) -> PreparedContext:
    """Build a minimal PreparedContext for testing."""
    return PreparedContext(
        decision=RoutingDecision(
            route=RouteType.LOCAL, reason=reason, confidence=None,
            pii_detected=False, query_hash="test123",
            timestamp=datetime.now(timezone.utc).isoformat(),
            cosine_gate_fired=cosine_gate_fired,
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


@patch("core.cognition.pipeline.postprocess.score_response")
def test_clean_response_passes_through(mock_score):
    mock_score.return_value = ConfidenceResult(score=85.0, method="logprob")
    prep = _make_prep(reason="test (no NLI trigger)")
    result = post_process("Hello, this is a clean response.", None, prep, "qwen2.5:14b")
    assert not result.is_hard_veto
    assert result.text == "Hello, this is a clean response."
    assert result.confidence.score == 85.0


@patch("core.cognition.pipeline.postprocess.score_response")
def test_json_preamble_stripped(mock_score):
    mock_score.return_value = ConfidenceResult(score=80.0, method="logprob")
    prep = _make_prep(reason="no trigger")
    text_with_preamble = '{"contains_assertion": false} Actual response here.'
    result = post_process(text_with_preamble, None, prep, "qwen2.5:14b")
    assert "contains_assertion" not in result.text
    assert "Actual response here." in result.text


@patch("core.cognition.pipeline.postprocess.score_response")
def test_oauth_provider_skips_nli(mock_score):
    """When routed via OAuth provider, NLI stage is skipped."""
    mock_score.return_value = ConfidenceResult(score=90.0, method="logprob")
    prep = _make_prep(reason="anthropic-oauth override")
    result = post_process("Some response.", None, prep, "claude-sonnet-4-6")
    assert result.confidence.score == 90.0
    assert not result.is_hard_veto


@patch("core.cognition.pipeline.postprocess.score_response")
@patch("core.identity.contradiction.check_contradiction")
@patch("core.memory.search.hybrid_search")
def test_identity_contradiction_hard_veto(mock_search, mock_nli, mock_score):
    """Identity contradiction with >=60% confidence triggers hard veto."""
    mock_score.return_value = ConfidenceResult(score=85.0, method="logprob")
    mock_search.return_value = [MagicMock(source_path="core.md", content="I am KAIROS")]
    mock_nli.return_value = MagicMock(
        has_contradiction=True, contradiction_type="identity", confidence=75,
    )
    prep = _make_prep(reason="Force-local test", cosine_gate_fired=True)
    result = post_process("I am not KAIROS", None, prep, "qwen2.5:14b")
    assert result.is_hard_veto
    assert result.confidence.score == 0.0
    assert "HARD VETO" in result.text


@patch("core.cognition.pipeline.postprocess.score_response")
def test_returns_post_process_result(mock_score):
    """Return type is always PostProcessResult."""
    mock_score.return_value = ConfidenceResult(score=75.0, method="degraded")
    prep = _make_prep(reason="no trigger")
    result = post_process("Any response.", None, prep, "qwen2.5:14b")
    assert isinstance(result, PostProcessResult)
    assert isinstance(result.warnings, list)
    assert result.contradiction is None


@patch("core.cognition.pipeline.postprocess.score_response")
@patch("core.identity.contradiction.check_contradiction")
@patch("core.memory.search.hybrid_search")
def test_knowledge_contradiction_applies_penalty(mock_search, mock_nli, mock_score):
    """Knowledge contradiction with >=60% confidence reduces confidence score."""
    mock_score.return_value = ConfidenceResult(score=70.0, method="logprob")
    mock_search.return_value = []
    mock_nli.return_value = MagicMock(
        has_contradiction=True, contradiction_type="knowledge", confidence=65,
    )
    prep = _make_prep(reason="Force-local test", cosine_gate_fired=True)
    result = post_process("Some answer.", None, prep, "qwen2.5:14b")
    assert not result.is_hard_veto
    assert result.confidence.score == 50.0  # 70 - 20 penalty


@patch("core.cognition.pipeline.postprocess.score_response")
def test_nli_not_triggered_without_gate_or_keyword(mock_score):
    """NLI skipped when cosine gate not fired and no mission keyword in query."""
    mock_score.return_value = ConfidenceResult(score=80.0, method="logprob")
    prep = _make_prep(reason="High confidence", cosine_gate_fired=False)
    with patch("core.identity.contradiction.check_contradiction") as mock_nli:
        result = post_process("What is the capital of France?", None, prep, "qwen2.5:14b")
    mock_nli.assert_not_called()
    assert result.contradiction is None


@patch("core.cognition.pipeline.postprocess.score_response")
def test_mission_keyword_triggers_nli(mock_score):
    """Mission keyword in query triggers NLI even without cosine gate."""
    mock_score.return_value = ConfidenceResult(score=80.0, method="logprob")
    prep = _make_prep(reason="High confidence", cosine_gate_fired=False)
    prep = PreparedContext(
        decision=prep.decision,
        pii_result=prep.pii_result,
        effective_query="Should I give up on my goals?",
        pii_scrubbed=prep.pii_scrubbed,
        compiled=prep.compiled,
        context_block=prep.context_block,
        system_prompt=prep.system_prompt,
        full_prompt=prep.full_prompt,
        session=prep.session,
        qhash=prep.qhash,
    )
    no_contradiction = MagicMock(
        has_contradiction=False, contradiction_type="none", confidence=0,
    )
    with (
        patch("core.memory.search.hybrid_search", return_value=[]),
        patch("core.identity.contradiction.check_contradiction", return_value=no_contradiction) as mock_nli,
    ):
        result = post_process("You should not give up.", None, prep, "qwen2.5:14b")
    mock_nli.assert_called_once()


@patch("core.cognition.pipeline.postprocess.score_response")
def test_skip_nli_bypasses_mission_keyword_trigger(mock_score):
    """T-120b: skip_nli=True prevents NLI even when mission keywords match."""
    mock_score.return_value = ConfidenceResult(score=80.0, method="logprob")
    prep = _make_prep(reason="Force-local test", cosine_gate_fired=True)
    prep = PreparedContext(
        decision=prep.decision,
        pii_result=prep.pii_result,
        effective_query="Should I give up on my goals?",
        pii_scrubbed=prep.pii_scrubbed,
        compiled=prep.compiled,
        context_block=prep.context_block,
        system_prompt=prep.system_prompt,
        full_prompt=prep.full_prompt,
        session=prep.session,
        qhash=prep.qhash,
    )
    with patch("core.identity.contradiction.check_contradiction") as mock_nli:
        result = post_process("You should not give up.", None, prep, "qwen2.5:14b", skip_nli=True)
    mock_nli.assert_not_called()
    assert not result.is_hard_veto


@patch("core.cognition.pipeline.postprocess.score_response")
def test_skip_nli_false_still_triggers(mock_score):
    """skip_nli=False (default) still triggers NLI on mission keywords."""
    mock_score.return_value = ConfidenceResult(score=80.0, method="logprob")
    prep = _make_prep(reason="Force-local test", cosine_gate_fired=True)
    prep = PreparedContext(
        decision=prep.decision,
        pii_result=prep.pii_result,
        effective_query="Should I give up?",
        pii_scrubbed=prep.pii_scrubbed,
        compiled=prep.compiled,
        context_block=prep.context_block,
        system_prompt=prep.system_prompt,
        full_prompt=prep.full_prompt,
        session=prep.session,
        qhash=prep.qhash,
    )
    no_contradiction = MagicMock(
        has_contradiction=False, contradiction_type="none", confidence=0,
    )
    with (
        patch("core.memory.search.hybrid_search", return_value=[]),
        patch("core.identity.contradiction.check_contradiction", return_value=no_contradiction) as mock_nli,
    ):
        result = post_process("Never give up.", None, prep, "qwen2.5:14b", skip_nli=False)
    mock_nli.assert_called_once()
