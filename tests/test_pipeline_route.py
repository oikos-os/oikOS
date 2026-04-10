"""Tests for pipeline/route.py — routing decision stage."""

from unittest.mock import patch

from core.interface.models import PIIResult, RouteType


def _pii_clean():
    return PIIResult(has_pii=False, entities=[])


def test_force_local():
    from core.cognition.pipeline.route import make_routing_decision

    decision = make_routing_decision("hello", _pii_clean(), "abc123", force_local=True)
    assert decision.route == RouteType.LOCAL
    assert "Forced local" in decision.reason


def test_force_cloud():
    from core.cognition.pipeline.route import make_routing_decision

    decision = make_routing_decision("hello", _pii_clean(), "abc123", force_cloud=True)
    assert decision.route == RouteType.CLOUD
    assert "Forced cloud" in decision.reason


@patch("core.cognition.routing.route_query")
@patch("core.memory.embedder.embed_single", side_effect=ConnectionError)
@patch("core.cognition.complexity.score_complexity", return_value={"penalty": 50})
def test_auto_routing(mock_complexity, mock_embed, mock_route):
    from core.cognition.pipeline.route import make_routing_decision

    mock_route.return_value = type("D", (), {
        "route": RouteType.LOCAL, "reason": "auto", "confidence": None,
        "pii_detected": False, "query_hash": "abc", "timestamp": "t",
    })()

    decision = make_routing_decision("hello", _pii_clean(), "abc123")
    mock_route.assert_called_once()
    assert mock_route.call_args[1]["complexity"] == {"penalty": 50}
    assert mock_route.call_args[1]["query_vector"] is None


@patch("core.cognition.routing.route_query")
@patch("core.cognition.complexity.score_complexity", side_effect=RuntimeError("boom"))
def test_complexity_failure_non_blocking(mock_complexity, mock_route):
    from core.cognition.pipeline.route import make_routing_decision

    mock_route.return_value = type("D", (), {
        "route": RouteType.LOCAL, "reason": "auto", "confidence": None,
        "pii_detected": False, "query_hash": "abc", "timestamp": "t",
    })()

    decision = make_routing_decision("hello", _pii_clean(), "abc123")
    mock_route.assert_called_once()
    assert mock_route.call_args[1]["complexity"] is None
