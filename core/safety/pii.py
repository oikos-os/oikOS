"""PII detection, anonymization, and detection logging via Presidio."""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from core.interface.config import (
    PII_CONFIDENCE_THRESHOLD,
    PII_ENTITY_TYPES,
    PII_LOG_DIR,
    PII_SPACY_MODEL,
)
from core.interface.models import PIIEntity, PIIResult

if TYPE_CHECKING:
    from presidio_analyzer import AnalyzerEngine
    from presidio_anonymizer import AnonymizerEngine

log = logging.getLogger(__name__)

_analyzer: AnalyzerEngine | None = None
_anonymizer: AnonymizerEngine | None = None


def get_analyzer() -> AnalyzerEngine:
    """Lazy-loaded singleton AnalyzerEngine."""
    global _analyzer
    if _analyzer is None:
        from presidio_analyzer import AnalyzerEngine
        from presidio_analyzer.nlp_engine import NlpEngineProvider

        provider = NlpEngineProvider(nlp_configuration={
            "nlp_engine_name": "spacy",
            "models": [{"lang_code": "en", "model_name": PII_SPACY_MODEL}],
        })
        _analyzer = AnalyzerEngine(nlp_engine=provider.create_engine())
    return _analyzer


def get_anonymizer() -> AnonymizerEngine:
    """Lazy-loaded singleton AnonymizerEngine."""
    global _anonymizer
    if _anonymizer is None:
        from presidio_anonymizer import AnonymizerEngine
        _anonymizer = AnonymizerEngine()
    return _anonymizer


_PII_WHITELIST = {
    # Project names (add your own to prevent false PII detection)
    "oikos", "oikos omega",

    # Financial entities (avoid false positives)
    "apple card", "discover card", "discover",

    # Add your own known entities below
    "george",
}

_SINGLE_DIGITS: dict[str, str] = {
    "zero": "0", "oh": "0",
    "one": "1", "two": "2", "three": "3", "four": "4",
    "five": "5", "six": "6", "seven": "7", "eight": "8", "nine": "9",
}

# Tokens that can legally start a multi-word compound cardinal (w2n gate)
_COMPOUND_STARTERS: frozenset[str] = frozenset({
    "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen",
    "seventeen", "eighteen", "nineteen",
    "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety",
    "hundred", "thousand", "million", "billion",
})


def _normalize_word_numbers(text: str) -> str:
    """Convert word-form digit sequences to numeric strings.

    Single-digit run gate: consecutive cardinal words (≥2) joined into one numeric token.
    Lone single-digit words (run=1) are left unchanged (adjacency gate not met).
    Compound cardinal gate: word2number windows 2–5, only fires for tokens in
    _COMPOUND_STARTERS to prevent w2n's permissive skip-and-accumulate behavior from
    consuming non-number tokens.
    Ordinals (first/second/third) pass through unchanged — not in _SINGLE_DIGITS or
    _COMPOUND_STARTERS, and w2n raises ValueError on them.
    """
    from word2number import w2n

    tokens = text.split()
    result_tokens: list[str] = []
    i = 0
    while i < len(tokens):
        clean = tokens[i].lower().rstrip(".,;:!?")

        # Single-digit run gate — adjacency ≥ 2 required
        if clean in _SINGLE_DIGITS:
            run: list[str] = []
            j = i
            while j < len(tokens) and tokens[j].lower().rstrip(".,;:!?") in _SINGLE_DIGITS:
                run.append(_SINGLE_DIGITS[tokens[j].lower().rstrip(".,;:!?")])
                j += 1
            if len(run) >= 2:
                result_tokens.append("".join(run))
                i = j
            else:
                # Lone single-digit: leave unchanged, never fall through to compound gate
                result_tokens.append(tokens[i])
                i += 1
            continue

        # Compound cardinal gate — only for known multi-word number starters
        # Guard prevents w2n's skip-non-number-words behavior from eating adjacent tokens
        if clean in _COMPOUND_STARTERS:
            converted = False
            for size in range(min(5, len(tokens) - i), 1, -1):
                candidate = " ".join(t.lower() for t in tokens[i:i + size])
                try:
                    numeric = w2n.word_to_num(candidate)
                    result_tokens.append(str(numeric))
                    i += size
                    converted = True
                    break
                except (ValueError, IndexError, AttributeError):
                    pass
            if not converted:
                result_tokens.append(tokens[i])
                i += 1
            continue

        result_tokens.append(tokens[i])
        i += 1

    return " ".join(result_tokens)


def _normalize_for_pii(text: str) -> str:
    """Pre-process text to catch obfuscated PII formats.

    Presidio is pattern-based and misses creative formatting like:
    - SSN: "1-2-3, 4-5, 6-7-8-9" → "123-45-6789"
    - Phone: "555 . 867 . 5309" → "555-867-5309"

    Strategy: Find digit sequences with non-standard delimiters, normalize to standard format.
    """
    import re

    # Pattern: 9 digits with any delimiters (SSN candidates)
    ssn_pattern = r'\b(\d[\s\-,\.]*){8}\d\b'
    for match in re.finditer(ssn_pattern, text):
        original = match.group()
        digits = re.sub(r'[^\d]', '', original)
        if len(digits) == 9:
            # Reformat as standard SSN: XXX-XX-XXXX
            standard_ssn = f'{digits[:3]}-{digits[3:5]}-{digits[5:]}'
            text = text.replace(original, standard_ssn)

    # Pattern: 10 digits with any delimiters (US phone candidates)
    phone_pattern = r'\b(\d[\s\-,\.]*){9}\d\b'
    for match in re.finditer(phone_pattern, text):
        original = match.group()
        digits = re.sub(r'[^\d]', '', original)
        if len(digits) == 10:
            # Reformat as standard phone: XXX-XXX-XXXX
            standard_phone = f'{digits[:3]}-{digits[3:6]}-{digits[6:]}'
            text = text.replace(original, standard_phone)

    return text


def detect_pii(text: str) -> PIIResult:
    """Analyze text for PII entities. No anonymization.

    Includes pre-processing normalization to catch obfuscated formats.
    """
    # Normalize to catch obfuscated PII (word-number + delimiter normalization)
    normalized_text = _normalize_for_pii(_normalize_word_numbers(text))

    analyzer = get_analyzer()
    results = analyzer.analyze(
        text=normalized_text,
        entities=PII_ENTITY_TYPES,
        language="en",
        score_threshold=PII_CONFIDENCE_THRESHOLD,
    )

    # Filter whitelist (strip possessives before checking)
    results = [
        r for r in results
        if normalized_text[r.start:r.end].lower().rstrip("'s") not in _PII_WHITELIST
    ]

    entities = [
        PIIEntity(
            entity_type=r.entity_type,
            text=normalized_text[r.start:r.end],
            start=r.start,
            end=r.end,
            score=r.score,
        )
        for r in results
    ]
    return PIIResult(has_pii=len(entities) > 0, entities=entities)


def scrub_pii(text: str) -> PIIResult:
    """Detect PII and replace with numbered placeholders. Returns result with anonymization map."""
    effective_text = _normalize_for_pii(_normalize_word_numbers(text))

    analyzer = get_analyzer()

    analysis_results = analyzer.analyze(
        text=effective_text,
        entities=PII_ENTITY_TYPES,
        language="en",
        score_threshold=PII_CONFIDENCE_THRESHOLD,
    )

    # Filter whitelist (strip possessives before checking)
    analysis_results = [
        r for r in analysis_results
        if effective_text[r.start:r.end].lower().rstrip("'s") not in _PII_WHITELIST
    ]

    if not analysis_results:
        return PIIResult(has_pii=False, entities=[], scrubbed_text=text)

    entities = [
        PIIEntity(
            entity_type=r.entity_type,
            text=effective_text[r.start:r.end],
            start=r.start,
            end=r.end,
            score=r.score,
        )
        for r in analysis_results
    ]

    # Build numbered placeholders per entity type
    type_counts: dict[str, int] = {}
    anonymization_map: dict[str, str] = {}
    operators: dict[str, OperatorConfig] = {}

    # Sort by start position for deterministic numbering
    sorted_results = sorted(analysis_results, key=lambda r: r.start)
    for r in sorted_results:
        type_counts.setdefault(r.entity_type, 0)
        type_counts[r.entity_type] += 1
        n = type_counts[r.entity_type]
        placeholder = f"<{r.entity_type}_{n}>"
        anonymization_map[placeholder] = effective_text[r.start:r.end]

    # Build scrubbed text with numbered placeholders (forward pass, offset-adjusted)
    type_idx: dict[str, int] = {}
    scrubbed = effective_text
    offset = 0
    for r in sorted(analysis_results, key=lambda r: r.start):
        type_idx.setdefault(r.entity_type, 0)
        type_idx[r.entity_type] += 1
        placeholder = f"<{r.entity_type}_{type_idx[r.entity_type]}>"
        start = r.start + offset
        end = r.end + offset
        scrubbed = scrubbed[:start] + placeholder + scrubbed[end:]
        offset += len(placeholder) - (r.end - r.start)

    return PIIResult(
        has_pii=True,
        entities=entities,
        scrubbed_text=scrubbed,
        anonymization_map=anonymization_map,
    )


def restore_pii(text: str, anonymization_map: dict[str, str]) -> str:
    """Replace placeholders with original PII values."""
    result = text
    for placeholder, original in anonymization_map.items():
        result = result.replace(placeholder, original)
    return result


def log_detection(pii_result: PIIResult, query_hash: str) -> None:
    """Append PII detection entry to JSONL log. Entity text is NOT logged."""
    PII_LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_file = PII_LOG_DIR / f"{datetime.now(timezone.utc).strftime('%Y-%m-%d')}.jsonl"

    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "query_hash": query_hash,
        "entities_found": [
            {"type": e.entity_type, "score": e.score}
            for e in pii_result.entities
        ],
        "entity_count": len(pii_result.entities),
    }

    with open(log_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")
