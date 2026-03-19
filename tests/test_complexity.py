"""Tests for core/complexity.py — pre-inference query complexity scorer."""

from __future__ import annotations

from unittest.mock import patch

from core.cognition.complexity import (
    ABSTRACT_KEYWORDS,
    CREATIVE_KEYWORDS,
    score_complexity,
)


class TestScoreComplexity:
    """score_complexity returns penalty, signals, and skip_local flag."""

    def test_simple_query_no_penalty(self):
        result = score_complexity("What is my name?")
        assert result["penalty"] == 0
        assert result["signals"] == []
        assert result["skip_local"] is False

    def test_length_signal(self):
        # 50+ tokens should trigger length penalty
        long_query = "Tell me about " + " ".join(["something"] * 60)
        result = score_complexity(long_query)
        assert any("length:" in s for s in result["signals"])
        assert result["penalty"] >= 10.0

    def test_abstract_keywords_signal(self):
        result = score_complexity("Analyze the strategic implications of this approach")
        assert any("abstract:" in s for s in result["signals"])
        assert result["penalty"] >= 15.0

    def test_creative_keywords_signal(self):
        result = score_complexity("Write a narrative about the character's aesthetic")
        assert any("creative:" in s for s in result["signals"])
        assert result["penalty"] >= 15.0

    def test_multi_domain_signal(self):
        # Patch domain map to return known domains
        mock_domains = {
            "music": {"trendy", "decay"},
            "literature": {"arcadia", "heights"},
        }
        with patch("core.cognition.complexity._get_domain_map", return_value=mock_domains):
            result = score_complexity("How does example project relate to example novel")
            assert any("multi-domain:" in s for s in result["signals"])
            assert result["penalty"] >= 15.0

    def test_stacked_signals(self):
        """Multiple signals stack penalties."""
        mock_domains = {
            "music": {"trendy", "decay"},
            "oikos": {"oikos", "sovereign"},
        }
        with patch("core.cognition.complexity._get_domain_map", return_value=mock_domains):
            # Abstract + multi-domain + long
            query = "Analyze the strategic " + " ".join(["implications"] * 50) + " of example project and oikos"
            result = score_complexity(query)
            assert result["penalty"] >= 30.0
            assert result["skip_local"] is True
            assert len(result["signals"]) >= 2

    def test_skip_local_threshold(self):
        """skip_local requires 2+ signals (penalty > 20) in balanced posture."""
        # Single abstract signal → penalty 15 → skip_local False (below 20 threshold)
        result = score_complexity("Analyze the strategic implications")
        assert result["penalty"] >= 15.0
        assert result["skip_local"] is False  # single signal not enough

    def test_skip_local_two_signals(self):
        """Two signals stack above threshold → skip_local True."""
        # Abstract + creative → penalty 30 → skip_local True
        result = score_complexity("Analyze the narrative aesthetic implications")
        assert result["penalty"] >= 30.0
        assert result["skip_local"] is True

    def test_skip_local_false_for_simple(self):
        result = score_complexity("Hello")
        assert result["skip_local"] is False

    def test_penalty_clamped_at_100(self):
        """Penalty never exceeds 100."""
        mock_domains = {
            "music": {"trendy", "decay"},
            "literature": {"arcadia", "heights"},
        }
        with patch("core.cognition.complexity._get_domain_map", return_value=mock_domains):
            query = (
                "Analyze and synthesize the strategic creative narrative implications "
                "of example project and example novel " + " ".join(["word"] * 60)
            )
            result = score_complexity(query)
            assert result["penalty"] <= 100.0

    def test_domains_matched_returned(self):
        mock_domains = {"oikos": {"oikos"}}
        with patch("core.cognition.complexity._get_domain_map", return_value=mock_domains):
            result = score_complexity("How does oikos work?")
            assert "oikos" in result["domains_matched"]

    def test_token_count_returned(self):
        result = score_complexity("Hello world")
        assert result["token_count"] > 0


class TestKeywordSets:
    """Verify keyword sets contain expected terms."""

    def test_abstract_keywords_not_empty(self):
        assert len(ABSTRACT_KEYWORDS) > 10

    def test_creative_keywords_not_empty(self):
        assert len(CREATIVE_KEYWORDS) > 10

    def test_no_overlap_abstract_creative(self):
        overlap = ABSTRACT_KEYWORDS & CREATIVE_KEYWORDS
        assert len(overlap) == 0, f"Overlap: {overlap}"


class TestRoutingIntegration:
    """Complexity integrates with route_query."""

    def test_complexity_triggers_cloud_route(self):
        from core.interface.models import PIIResult, RouteType
        from core.cognition.routing import route_query

        pii = PIIResult(has_pii=False, entities=[])
        complexity = {"penalty": 20.0, "signals": ["abstract:strategy"], "skip_local": True}

        decision = route_query("strategy query", pii, None, complexity=complexity)
        assert decision.route == RouteType.CLOUD
        assert "Complexity pre-score" in decision.reason

    def test_complexity_no_trigger_when_penalty_low(self):
        from core.interface.models import PIIResult, RouteType
        from core.cognition.routing import route_query

        pii = PIIResult(has_pii=False, entities=[])
        complexity = {"penalty": 5.0, "signals": [], "skip_local": False}

        decision = route_query("simple query", pii, None, complexity=complexity)
        assert decision.route == RouteType.LOCAL

    def test_pii_overrides_complexity(self):
        from core.interface.models import PIIEntity, PIIResult, RouteType
        from core.cognition.routing import route_query

        pii = PIIResult(
            has_pii=True,
            entities=[PIIEntity(entity_type="PERSON", text="X", start=0, end=1, score=0.9)],
        )
        complexity = {"penalty": 50.0, "signals": ["abstract:strategy"], "skip_local": True}

        decision = route_query("strategy about person X", pii, None, complexity=complexity)
        assert decision.route == RouteType.LOCAL
        assert "PII" in decision.reason

    def test_force_local_pattern_overrides_complexity(self):
        from core.interface.models import PIIResult, RouteType
        from core.cognition.routing import route_query

        pii = PIIResult(has_pii=False, entities=[])
        complexity = {"penalty": 50.0, "signals": ["abstract:strategy"], "skip_local": True}

        decision = route_query("analyze the sovereign identity", pii, None, complexity=complexity)
        assert decision.route == RouteType.LOCAL
        assert "Force-local" in decision.reason

    def test_complexity_with_existing_confidence(self):
        """When confidence is provided, penalty is subtracted from it."""
        from core.interface.models import ConfidenceResult, PIIResult, RouteType
        from core.cognition.routing import route_query

        pii = PIIResult(has_pii=False, entities=[])
        confidence = ConfidenceResult(score=70.0, method="test")
        complexity = {"penalty": 15.0, "signals": ["abstract:analyze"], "skip_local": True}

        decision = route_query("analyze this", pii, confidence, complexity=complexity)
        # 70 - 15 = 55 < 60 threshold → cloud
        assert decision.route == RouteType.CLOUD
