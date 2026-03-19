"""Tests for PII detection and anonymization."""

from unittest.mock import MagicMock, patch

from core.interface.models import PIIEntity, PIIResult
from core.safety.pii import _normalize_word_numbers, detect_pii, log_detection, restore_pii, scrub_pii


def _mock_analyzer_result(entity_type, start, end, score=0.85):
    r = MagicMock()
    r.entity_type = entity_type
    r.start = start
    r.end = end
    r.score = score
    return r


@patch("core.safety.pii._analyzer")
def test_detect_pii_with_entities(mock_analyzer_global):
    text = "Call John at john@example.com"
    mock_analyzer = MagicMock()
    mock_analyzer.analyze.return_value = [
        _mock_analyzer_result("PERSON", 5, 9, 0.85),
        _mock_analyzer_result("EMAIL_ADDRESS", 13, 29, 0.95),
    ]
    with patch("core.safety.pii.get_analyzer", return_value=mock_analyzer):
        result = detect_pii(text)

    assert result.has_pii is True
    assert len(result.entities) == 2
    assert result.entities[0].entity_type == "PERSON"
    assert result.entities[1].entity_type == "EMAIL_ADDRESS"


@patch("core.safety.pii._analyzer")
def test_detect_pii_clean_text(mock_analyzer_global):
    mock_analyzer = MagicMock()
    mock_analyzer.analyze.return_value = []
    with patch("core.safety.pii.get_analyzer", return_value=mock_analyzer):
        result = detect_pii("The weather is nice today.")

    assert result.has_pii is False
    assert len(result.entities) == 0


@patch("core.safety.pii._analyzer")
def test_scrub_pii_replaces_entities(mock_analyzer_global):
    text = "Email john@test.com now"
    mock_analyzer = MagicMock()
    mock_analyzer.analyze.return_value = [
        _mock_analyzer_result("EMAIL_ADDRESS", 6, 19, 0.95),
    ]
    mock_anonymizer = MagicMock()

    with patch("core.safety.pii.get_analyzer", return_value=mock_analyzer), \
         patch("core.safety.pii.get_anonymizer", return_value=mock_anonymizer):
        result = scrub_pii(text)

    assert result.has_pii is True
    assert "<EMAIL_ADDRESS_1>" in result.scrubbed_text
    assert "john@test.com" not in result.scrubbed_text


@patch("core.safety.pii._analyzer")
def test_scrub_pii_returns_map(mock_analyzer_global):
    text = "Hi John, email john@test.com"
    mock_analyzer = MagicMock()
    mock_analyzer.analyze.return_value = [
        _mock_analyzer_result("PERSON", 3, 7, 0.85),
        _mock_analyzer_result("EMAIL_ADDRESS", 15, 28, 0.95),
    ]
    mock_anonymizer = MagicMock()

    with patch("core.safety.pii.get_analyzer", return_value=mock_analyzer), \
         patch("core.safety.pii.get_anonymizer", return_value=mock_anonymizer):
        result = scrub_pii(text)

    assert result.anonymization_map is not None
    assert "<PERSON_1>" in result.anonymization_map
    assert result.anonymization_map["<PERSON_1>"] == "John"


def test_restore_pii():
    scrubbed = "Hi <PERSON_1>, email <EMAIL_ADDRESS_1>"
    mapping = {
        "<PERSON_1>": "John",
        "<EMAIL_ADDRESS_1>": "john@test.com",
    }
    restored = restore_pii(scrubbed, mapping)
    assert restored == "Hi John, email john@test.com"


def test_log_detection_writes_jsonl(tmp_path):
    pii_result = PIIResult(
        has_pii=True,
        entities=[
            PIIEntity(entity_type="PERSON", text="John", start=0, end=4, score=0.85),
        ],
    )
    with patch("core.safety.pii.PII_LOG_DIR", tmp_path):
        log_detection(pii_result, "abc123")

    import json
    log_files = list(tmp_path.glob("*.jsonl"))
    assert len(log_files) == 1
    entry = json.loads(log_files[0].read_text(encoding="utf-8").strip())
    assert entry["query_hash"] == "abc123"
    assert entry["entity_count"] == 1
    assert entry["entities_found"][0]["type"] == "PERSON"


def test_log_detection_no_entity_text(tmp_path):
    pii_result = PIIResult(
        has_pii=True,
        entities=[
            PIIEntity(entity_type="EMAIL_ADDRESS", text="secret@mail.com", start=0, end=15, score=0.9),
        ],
    )
    with patch("core.safety.pii.PII_LOG_DIR", tmp_path):
        log_detection(pii_result, "def456")

    log_files = list(tmp_path.glob("*.jsonl"))
    raw = log_files[0].read_text(encoding="utf-8")
    assert "secret@mail.com" not in raw


def test_lazy_loading():
    """Analyzer not initialized until first call."""
    import core.safety.pii as pii_mod
    original = pii_mod._analyzer
    pii_mod._analyzer = None
    assert pii_mod._analyzer is None
    # Restore
    pii_mod._analyzer = original


# ── PII Whitelist tests ──────────────────────────────────────────


@patch("core.safety.pii._analyzer")
def test_whitelist_filters_detect_pii(mock_analyzer_global):
    """Whitelisted terms (e.g. 'Apex', 'Example Project') are not flagged as PII."""
    text = "Ask Apex about Example Project"
    mock_analyzer = MagicMock()
    mock_analyzer.analyze.return_value = [
        _mock_analyzer_result("PERSON", 4, 9, 0.85),       # "Apex"
        _mock_analyzer_result("ORGANIZATION", 16, 28, 0.80),  # "Example Project"
    ]
    with patch("core.safety.pii.get_analyzer", return_value=mock_analyzer):
        result = detect_pii(text)

    assert result.has_pii is False
    assert len(result.entities) == 0


@patch("core.safety.pii._analyzer")
def test_whitelist_filters_scrub_pii(mock_analyzer_global):
    """Whitelisted terms survive scrub_pii — text returned unmodified."""
    text = "Problem is the next release by Apex"
    mock_analyzer = MagicMock()
    mock_analyzer.analyze.return_value = [
        _mock_analyzer_result("PERSON", 0, 7, 0.70),       # "Problem"
        _mock_analyzer_result("PERSON", 31, 36, 0.85),     # "Apex"
    ]
    mock_anonymizer = MagicMock()
    with patch("core.safety.pii.get_analyzer", return_value=mock_analyzer), \
         patch("core.safety.pii.get_anonymizer", return_value=mock_anonymizer):
        result = scrub_pii(text)

    # All entities whitelisted -> no PII, scrubbed_text == original
    assert result.has_pii is False
    assert result.scrubbed_text == text


@patch("core.safety.pii._analyzer")
def test_whitelist_case_insensitive(mock_analyzer_global):
    """Whitelist matching is case-insensitive."""
    text = "USER and ACME CORP"
    mock_analyzer = MagicMock()
    mock_analyzer.analyze.return_value = [
        _mock_analyzer_result("PERSON", 0, 5, 0.85),         # "USER"
        _mock_analyzer_result("ORGANIZATION", 10, 20, 0.80),  # "ACME CORP"
    ]
    with patch("core.safety.pii.get_analyzer", return_value=mock_analyzer):
        result = detect_pii(text)

    assert result.has_pii is False


@patch("core.safety.pii._analyzer")
def test_whitelist_mixed_keeps_real_pii(mock_analyzer_global):
    """Non-whitelisted PII survives even when mixed with whitelisted terms."""
    text = "Email Apex and John at john@example.com"
    mock_analyzer = MagicMock()
    mock_analyzer.analyze.return_value = [
        _mock_analyzer_result("PERSON", 6, 11, 0.85),         # "Apex" (whitelisted)
        _mock_analyzer_result("PERSON", 16, 20, 0.90),        # "John" (NOT whitelisted)
        _mock_analyzer_result("EMAIL_ADDRESS", 24, 40, 0.95), # john@example.com
    ]
    with patch("core.safety.pii.get_analyzer", return_value=mock_analyzer):
        result = detect_pii(text)

    assert result.has_pii is True
    assert len(result.entities) == 2
    types = {e.entity_type for e in result.entities}
    assert "PERSON" in types
    assert "EMAIL_ADDRESS" in types
    # The PERSON entity should be "John", not "Apex"
    person_entities = [e for e in result.entities if e.entity_type == "PERSON"]
    assert person_entities[0].text == "John"


# ── Word-number normalization tests ─────────────────────────────


def test_normalize_word_numbers_phone_digits():
    """Consecutive single-digit run (≥2) collapses to numeric string."""
    text = "call nine one one five five five one two three four"
    result = _normalize_word_numbers(text)
    assert result == "call 9115551234"


def test_normalize_word_numbers_adjacency_gate_single():
    """Single isolated cardinal is not converted — adjacency gate not met."""
    text = "one of my projects"
    result = _normalize_word_numbers(text)
    assert result == "one of my projects"


def test_normalize_word_numbers_compound_cardinal():
    """Multi-word cardinal converted via word2number window."""
    text = "twenty three"
    result = _normalize_word_numbers(text)
    assert result == "23"


def test_normalize_word_numbers_ordinals_unchanged():
    """Ordinals are not in _SINGLE_DIGITS and raise ValueError in w2n — pass through unchanged."""
    text = "I am the first person in line"
    result = _normalize_word_numbers(text)
    assert result == "I am the first person in line"


@patch("core.safety.pii._analyzer")
def test_detect_pii_word_form_phone_detected(mock_analyzer_global):
    """Word-form phone number is normalized then detected by Presidio."""
    text = "nine one one five five five one two three four"
    # Normalized: "9115551234" — positions 0–10
    mock_analyzer = MagicMock()
    mock_analyzer.analyze.return_value = [
        _mock_analyzer_result("PHONE_NUMBER", 0, 10, 0.85),
    ]
    with patch("core.safety.pii.get_analyzer", return_value=mock_analyzer):
        result = detect_pii(text)

    assert result.has_pii is True
    assert len(result.entities) == 1
    assert result.entities[0].entity_type == "PHONE_NUMBER"


@patch("core.safety.pii._analyzer")
def test_scrub_pii_word_form_phone_scrubbed(mock_analyzer_global):
    """Word-form phone number is normalized, detected, and scrubbed to placeholder."""
    text = "call nine one one five five five one two three four please"
    # Normalization chain: word-numbers → "call 9115551234 please"
    #                      _normalize_for_pii → "call 911-555-1234 please" (10-digit reformat)
    # Phone at positions 5–17 in effective_text "call 911-555-1234 please"
    mock_analyzer = MagicMock()
    mock_analyzer.analyze.return_value = [
        _mock_analyzer_result("PHONE_NUMBER", 5, 17, 0.85),
    ]
    mock_anonymizer = MagicMock()

    with patch("core.safety.pii.get_analyzer", return_value=mock_analyzer), \
         patch("core.safety.pii.get_anonymizer", return_value=mock_anonymizer):
        result = scrub_pii(text)

    assert result.has_pii is True
    assert "<PHONE_NUMBER_1>" in result.scrubbed_text
    assert "9115551234" not in result.scrubbed_text
    assert result.anonymization_map["<PHONE_NUMBER_1>"] == "911-555-1234"
