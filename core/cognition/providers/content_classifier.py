"""ContentClassifier — 3-tier privacy classification for cloud routing.

Classification is DETERMINISTIC (regex + rules + Presidio). No LLM inference.
This prevents prompt injection from bypassing privacy controls.
"""

from __future__ import annotations

import re

from core.interface.models import DataTier

# --- NEVER_LEAVE patterns (hardcoded, not configurable) ---
_NEVER_LEAVE_PATTERNS = [
    re.compile(r"(?i)\bvault/identity\b"),
    re.compile(r"(?i)\bTELOS\b"),
    re.compile(r"(?i)\bMISSION\.md\b"),
    re.compile(r"(?i)\bBELIEFS\.md\b"),
    re.compile(r"(?i)\bGOALS\.md\b"),
    re.compile(r"(?i)\bMANIFESTO\.md\b"),
    re.compile(r"(?i)\bidentity[\\/]"),
    # API keys / credentials
    re.compile(r"(?i)\bapi[_\s-]?key\b"),
    re.compile(r"\bsk-[a-zA-Z0-9]{10,}"),  # OpenAI/Anthropic key pattern
    re.compile(r"\bAIza[a-zA-Z0-9_-]{30,}"),  # Google API key pattern
    re.compile(r"(?i)\bpassword\s*[:=]"),
    re.compile(r"(?i)\bsecret\s*[:=]"),
    re.compile(r"(?i)\bcredential"),
    # Identity markers
    re.compile(r"\barodri311\b"),
    re.compile(r"\bOIKOS_SIGMA\b"),
    re.compile(r"\bKAIROS\s+PRIME\b"),
    # AWS keys
    re.compile(r"\bAKIA[A-Z0-9]{16}\b"),
    # Private key material
    re.compile(r"-----BEGIN.*PRIVATE KEY-----"),
    # JWT tokens
    re.compile(r"\beyJ[a-zA-Z0-9_-]+\.eyJ[a-zA-Z0-9_-]+"),
]


class ContentClassifier:
    """Classify content into privacy tiers before cloud routing.

    Tier 0 (NEVER_LEAVE): Identity data, API keys, credentials — blocked entirely.
    Tier 1 (SENSITIVE): PII detected — anonymize before cloud dispatch.
    Tier 2 (SAFE): No PII, no identity — route freely.
    """

    def classify(self, content: str) -> DataTier:
        # Tier 0: NEVER_LEAVE — hardcoded, checked first
        for pattern in _NEVER_LEAVE_PATTERNS:
            if pattern.search(content):
                return DataTier.NEVER_LEAVE

        # Tier 1: SENSITIVE — PII detected via Presidio
        from core.safety.pii import detect_pii
        pii_result = detect_pii(content)
        if pii_result.has_pii:
            return DataTier.SENSITIVE

        # Tier 2: SAFE
        return DataTier.SAFE

    def anonymize(self, content: str) -> tuple[str, dict[str, str]]:
        """Anonymize content, returning (anonymized_text, mapping)."""
        from core.safety.pii import scrub_pii
        result = scrub_pii(content)
        if result.has_pii and result.scrubbed_text:
            return result.scrubbed_text, result.anonymization_map or {}
        return content, {}

    def deanonymize(self, text: str, anonymization_map: dict[str, str]) -> str:
        """Restore original entities from anonymized response."""
        for placeholder, original in anonymization_map.items():
            text = text.replace(placeholder, original)
        return text
