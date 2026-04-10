"""Tests for query routing engine."""

import json
from unittest.mock import patch

from core.interface.models import ConfidenceResult, PIIEntity, PIIResult, RoutingDecision, RouteType
from core.cognition.routing import backfill_user_accepted, log_routing_decision, query_hash, route_query


def _clean_pii():
    return PIIResult(has_pii=False, entities=[])


def _pii_with_person():
    return PIIResult(
        has_pii=True,
        entities=[PIIEntity(entity_type="PERSON", text="John", start=0, end=4, score=0.9)],
    )


def _confidence(score, method="logprobs"):
    return ConfidenceResult(score=score, method=method)


def test_route_pii_detected_forces_local():
    decision = route_query("Tell me about John", _pii_with_person(), _confidence(80))
    assert decision.route == RouteType.LOCAL
    assert "PII detected" in decision.reason
    assert decision.pii_detected is True


def test_route_force_local_pattern_telos():
    decision = route_query("What does TELOS say?", _clean_pii(), _confidence(80))
    assert decision.route == RouteType.LOCAL
    assert "Force-local pattern" in decision.reason


def test_route_force_local_pattern_vault():
    decision = route_query("Read vault/identity files", _clean_pii(), _confidence(80))
    assert decision.route == RouteType.LOCAL
    assert "Force-local pattern" in decision.reason


def test_route_force_local_multi_pattern():
    decision = route_query("Is the TELOS sovereign?", _clean_pii(), _confidence(80))
    assert decision.route == RouteType.LOCAL
    assert "TELOS" in decision.reason
    assert "sovereign" in decision.reason


def test_route_high_confidence_local():
    decision = route_query("What is Python?", _clean_pii(), _confidence(75))
    assert decision.route == RouteType.LOCAL
    assert ">=" in decision.reason


def test_route_low_confidence_cloud():
    decision = route_query("Explain quantum computing", _clean_pii(), _confidence(45))
    assert decision.route == RouteType.CLOUD
    assert "< 60.0%" in decision.reason


def test_route_no_confidence_defaults_local():
    decision = route_query("Simple question", _clean_pii(), None)
    assert decision.route == RouteType.LOCAL
    assert "defaulting to local" in decision.reason


def test_log_routing_decision_writes_jsonl(tmp_path):
    decision = RoutingDecision(
        route=RouteType.LOCAL,
        reason="test",
        confidence=ConfidenceResult(score=72.5, method="logprobs"),
        pii_detected=False,
        query_hash="abc123",
        timestamp="2026-02-12T00:00:00",
    )
    with patch("core.cognition.routing.ROUTING_LOG_DIR", tmp_path):
        log_routing_decision(decision)

    log_files = list(tmp_path.glob("*.jsonl"))
    assert len(log_files) == 1
    entry = json.loads(log_files[0].read_text(encoding="utf-8").strip())
    assert entry["query_hash"] == "abc123"
    assert entry["confidence_score"] == 72.5
    assert entry["route_taken"] == "local"
    assert entry["user_accepted"] is None


def test_query_hash_deterministic():
    h1 = query_hash("test query")
    h2 = query_hash("test query")
    assert h1 == h2
    assert len(h1) == 16


# ── Feedback backfill ────────────────────────────────────────────────


def test_backfill_user_accepted_true(tmp_path):
    """Backfill accept signal into routing log."""
    decision = RoutingDecision(
        route=RouteType.LOCAL, reason="test",
        confidence=ConfidenceResult(score=70.0, method="logprobs"),
        pii_detected=False, query_hash="feedbackhash1", timestamp="2026-02-13T00:00:00",
    )
    with patch("core.cognition.routing.ROUTING_LOG_DIR", tmp_path):
        log_routing_decision(decision)
        result = backfill_user_accepted("feedbackhash1", True)

    assert result is True
    log_files = list(tmp_path.glob("*.jsonl"))
    entry = json.loads(log_files[0].read_text(encoding="utf-8").strip())
    assert entry["user_accepted"] is True


def test_backfill_user_accepted_false(tmp_path):
    """Backfill reject signal."""
    decision = RoutingDecision(
        route=RouteType.LOCAL, reason="test",
        confidence=ConfidenceResult(score=70.0, method="logprobs"),
        pii_detected=False, query_hash="feedbackhash2", timestamp="2026-02-13T00:00:00",
    )
    with patch("core.cognition.routing.ROUTING_LOG_DIR", tmp_path):
        log_routing_decision(decision)
        result = backfill_user_accepted("feedbackhash2", False)

    assert result is True
    entry = json.loads(list(tmp_path.glob("*.jsonl"))[0].read_text(encoding="utf-8").strip())
    assert entry["user_accepted"] is False


def test_backfill_user_accepted_skip(tmp_path):
    """Backfill skip (None) signal."""
    decision = RoutingDecision(
        route=RouteType.LOCAL, reason="test",
        confidence=ConfidenceResult(score=70.0, method="logprobs"),
        pii_detected=False, query_hash="feedbackhash3", timestamp="2026-02-13T00:00:00",
    )
    with patch("core.cognition.routing.ROUTING_LOG_DIR", tmp_path):
        log_routing_decision(decision)
        result = backfill_user_accepted("feedbackhash3", None)

    assert result is True
    entry = json.loads(list(tmp_path.glob("*.jsonl"))[0].read_text(encoding="utf-8").strip())
    assert entry["user_accepted"] is None


def test_backfill_no_match(tmp_path):
    """No matching query_hash returns False."""
    decision = RoutingDecision(
        route=RouteType.LOCAL, reason="test",
        confidence=ConfidenceResult(score=70.0, method="logprobs"),
        pii_detected=False, query_hash="existing", timestamp="2026-02-13T00:00:00",
    )
    with patch("core.cognition.routing.ROUTING_LOG_DIR", tmp_path):
        log_routing_decision(decision)
        result = backfill_user_accepted("nonexistent", True)

    assert result is False


def test_backfill_no_log_file(tmp_path):
    """No log file returns False."""
    with patch("core.cognition.routing.ROUTING_LOG_DIR", tmp_path):
        result = backfill_user_accepted("anything", True)
    assert result is False


def test_backfill_only_updates_most_recent(tmp_path):
    """Multiple entries with same hash — only most recent null gets updated."""
    d1 = RoutingDecision(
        route=RouteType.LOCAL, reason="first",
        confidence=ConfidenceResult(score=60.0, method="logprobs"),
        pii_detected=False, query_hash="dupehash", timestamp="2026-02-13T00:00:00",
    )
    d2 = RoutingDecision(
        route=RouteType.LOCAL, reason="second",
        confidence=ConfidenceResult(score=65.0, method="logprobs"),
        pii_detected=False, query_hash="dupehash", timestamp="2026-02-13T00:01:00",
    )
    with patch("core.cognition.routing.ROUTING_LOG_DIR", tmp_path):
        log_routing_decision(d1)
        log_routing_decision(d2)
        backfill_user_accepted("dupehash", True)

    lines = list(tmp_path.glob("*.jsonl"))[0].read_text(encoding="utf-8").strip().split("\n")
    first = json.loads(lines[0])
    second = json.loads(lines[1])
    # Only the second (most recent) should be updated
    assert first["user_accepted"] is None
    assert second["user_accepted"] is True
