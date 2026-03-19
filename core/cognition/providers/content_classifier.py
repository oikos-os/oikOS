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
    re.compile(r"\bsk-ant-api03-[a-zA-Z0-9_-]{20,}"),  # Anthropic API key
    re.compile(r"\bsk-proj-[a-zA-Z0-9]{20,}"),  # OpenAI project key
    re.compile(r"\bAIza[a-zA-Z0-9_-]{30,}"),  # Google API key pattern
    re.compile(r"\bghp_[a-zA-Z0-9]{36,}"),  # GitHub personal access token
    re.compile(r"\bgho_[a-zA-Z0-9]{36,}"),  # GitHub OAuth token
    re.compile(r"\bghs_[a-zA-Z0-9]{36,}"),  # GitHub app installation token
    re.compile(r"\bglpat-[a-zA-Z0-9_-]{20,}"),  # GitLab personal access token
    re.compile(r"\bxoxb-[0-9]+-[a-zA-Z0-9]+"),  # Slack bot token
    re.compile(r"\bSG\.[a-zA-Z0-9_-]{22}\.[a-zA-Z0-9_-]{43}"),  # SendGrid API key
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


_HIGH_ENTROPY_MIN_LENGTH = 32
_HIGH_ENTROPY_THRESHOLD = 4.5  # Shannon entropy bits — random base64 is ~5.2, CamelCase code is ~4.0-4.3


def _shannon_entropy(s: str) -> float:
    """Calculate Shannon entropy of a string in bits."""
    import math
    if not s:
        return 0.0
    freq: dict[str, int] = {}
    for c in s:
        freq[c] = freq.get(c, 0) + 1
    length = len(s)
    return -sum((count / length) * math.log2(count / length) for count in freq.values())


def _has_high_entropy_token(content: str) -> bool:
    """Check if content contains a high-entropy token that looks like a credential."""
    for word in content.split():
        if len(word) >= _HIGH_ENTROPY_MIN_LENGTH and _shannon_entropy(word) > _HIGH_ENTROPY_THRESHOLD:
            # Skip common high-entropy non-secrets
            if word.startswith(("http://", "https://", "sha256:", "sha1:", "D:/", "C:/", "D:\\", "C:\\")):
                continue
            # Skip dotted Python imports and CamelCase class names
            if "." in word and not any(c in word for c in "=+/"):
                continue
            return True
    return False


class ContentClassifier:
    """Classify content into privacy tiers before cloud routing.

    Tier 0 (NEVER_LEAVE): Identity data, API keys, credentials — blocked entirely.
    Tier 1 (SENSITIVE): PII detected — anonymize before cloud dispatch.
    Tier 2 (SAFE): No PII, no identity — route freely.
    """

    def classify(self, content: str) -> DataTier:
        # Tier 0: NEVER_LEAVE — hardcoded patterns checked first
        for pattern in _NEVER_LEAVE_PATTERNS:
            if pattern.search(content):
                return DataTier.NEVER_LEAVE

        # Tier 0: NEVER_LEAVE — high-entropy tokens (unknown credential formats)
        if _has_high_entropy_token(content):
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
