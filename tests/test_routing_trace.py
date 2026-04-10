"""Tests for RoutingTrace dataclass — badge rendering and serialization."""

from core.cognition.pipeline.trace import RoutingTrace


def test_trace_default_state():
    t = RoutingTrace()
    assert t.provider == ""
    assert t.model == ""
    assert not t.pii_anonymized
    assert not t.output_filtered
    assert not t.cosine_gate_fired
    assert not t.never_leave_fired
    assert not t.room_restricted
    assert not t.confidence_escalated
    assert t.content_class == ""
    assert t.complexity == ""


def test_badge_simple_query():
    t = RoutingTrace(provider="ollama/qwen2.5:7b", complexity="SIMPLE")
    assert t.badge_line() == "ollama/qwen2.5:7b · simple query"


def test_badge_complex_query():
    t = RoutingTrace(provider="gemini", complexity="COMPLEX")
    assert t.badge_line() == "gemini · complex query"


def test_badge_never_leave():
    t = RoutingTrace(provider="ollama", never_leave_fired=True, content_class="NEVER_LEAVE")
    assert t.badge_line() == "ollama · private content"


def test_badge_pii_anonymized():
    t = RoutingTrace(provider="gemini", complexity="COMPLEX", pii_anonymized=True)
    assert t.badge_line() == "gemini · complex query · pii anonymized"


def test_badge_output_filtered():
    t = RoutingTrace(provider="gemini", output_filtered=True)
    assert t.badge_line() == "gemini · content filtered"


def test_badge_cosine_gate():
    t = RoutingTrace(provider="ollama", cosine_gate_fired=True)
    assert t.badge_line() == "ollama · identity match"


def test_badge_room_restricted():
    t = RoutingTrace(provider="ollama", room_restricted=True, complexity="MODERATE")
    assert t.badge_line() == "ollama · room restricted"


def test_badge_confidence_escalation():
    t = RoutingTrace(provider="gemini", confidence_escalated=True, complexity="MODERATE")
    assert t.badge_line() == "gemini · confidence escalation"


def test_badge_priority_order():
    """NEVER_LEAVE + PII → primary is 'private content', PII shows as flag."""
    t = RoutingTrace(
        provider="ollama", never_leave_fired=True,
        pii_anonymized=True, content_class="NEVER_LEAVE",
    )
    badge = t.badge_line()
    assert badge.startswith("ollama · private content")
    assert "pii anonymized" in badge


def test_badge_flags_no_duplicate():
    """When PII is the primary reason, it shouldn't also appear in flags."""
    t = RoutingTrace(provider="gemini", pii_anonymized=True, complexity="")
    badge = t.badge_line()
    assert badge.count("pii anonymized") == 1


def test_to_dict_complete():
    t = RoutingTrace(
        provider="gemini", model="gemini-2.0-flash",
        content_class="SAFE", complexity="COMPLEX",
        pii_anonymized=True,
    )
    d = t.to_dict()
    assert d["provider"] == "gemini"
    assert d["model"] == "gemini-2.0-flash"
    assert d["content_class"] == "SAFE"
    assert d["complexity"] == "COMPLEX"
    assert d["pii_anonymized"] is True
    assert d["output_filtered"] is False
    assert "routing_reason" in d
    assert "badge" in d
    for key in ("cosine_gate_fired", "never_leave_fired", "room_restricted", "confidence_escalated"):
        assert key in d


def test_badge_length_under_80():
    """Various combinations stay under 80 chars."""
    cases = [
        RoutingTrace(provider="ollama/qwen2.5:14b", complexity="SIMPLE"),
        RoutingTrace(provider="gemini", complexity="COMPLEX", pii_anonymized=True),
        RoutingTrace(provider="anthropic/claude-sonnet", output_filtered=True, pii_anonymized=True),
        RoutingTrace(provider="ollama", never_leave_fired=True, pii_anonymized=True, content_class="NEVER_LEAVE"),
    ]
    for t in cases:
        assert len(t.badge_line()) <= 80, f"Badge too long: {t.badge_line()!r}"
