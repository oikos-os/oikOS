"""Routing trace — accumulates pipeline decisions for transparency."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class RoutingTrace:
    """Accumulates routing decisions through the inference pipeline."""

    # Provider selection
    provider: str = ""
    model: str = ""

    # Privacy/safety actions (zero or more, only set when triggered)
    pii_anonymized: bool = False
    output_filtered: bool = False
    cosine_gate_fired: bool = False
    never_leave_fired: bool = False
    room_restricted: bool = False
    confidence_escalated: bool = False

    # Classification metadata
    content_class: str = ""
    complexity: str = ""

    # T-118: Room generation param overrides (only set when Room overrides global)
    room_temperature: float | None = None
    room_max_tokens: int | None = None

    def badge_line(self) -> str:
        """Single-line human-readable routing summary (plain text)."""
        parts = [self.provider or "unknown"]
        reason = self._primary_reason()
        parts.append(reason)
        parts.extend(self._flags(reason))
        return " · ".join(parts)

    def _primary_reason(self) -> str:
        """Most significant routing reason, priority-ordered."""
        if self.output_filtered:
            return "content filtered"
        if self.never_leave_fired:
            return "private content"
        if self.cosine_gate_fired:
            return "identity match"
        if self.room_restricted:
            return "room restricted"
        if self.confidence_escalated:
            return "confidence escalation"
        if self.complexity:
            return self.complexity.lower() + " query"
        if self.pii_anonymized:
            return "pii anonymized"
        return "routed query"

    def _flags(self, primary: str) -> list[str]:
        """Additional flags beyond the primary reason."""
        flags: list[str] = []
        if self.pii_anonymized and primary != "pii anonymized":
            flags.append("pii anonymized")
        if self.output_filtered and primary != "content filtered":
            flags.append("content filtered")
        return flags

    def to_dict(self) -> dict:
        """Full trace for API responses."""
        d = {
            "badge": self.badge_line(),
            "provider": self.provider,
            "model": self.model,
            "routing_reason": self._primary_reason(),
            "content_class": self.content_class,
            "complexity": self.complexity,
            "pii_anonymized": self.pii_anonymized,
            "output_filtered": self.output_filtered,
            "cosine_gate_fired": self.cosine_gate_fired,
            "never_leave_fired": self.never_leave_fired,
            "room_restricted": self.room_restricted,
            "confidence_escalated": self.confidence_escalated,
        }
        if self.room_temperature is not None:
            d["room_temperature"] = self.room_temperature
        if self.room_max_tokens is not None:
            d["room_max_tokens"] = self.room_max_tokens
        return d
