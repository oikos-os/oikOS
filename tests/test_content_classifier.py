"""Tests for ContentClassifier — 3-tier privacy classification."""

from unittest.mock import patch

import pytest

from core.cognition.providers.content_classifier import ContentClassifier
from core.interface.models import DataTier, PIIResult, PIIEntity


@pytest.fixture
def classifier():
    return ContentClassifier()


class TestClassify:
    def test_safe_general_query(self, classifier):
        # Mock out PII detection to return no PII for general queries
        pii_result = PIIResult(has_pii=False, entities=[])
        with patch("core.safety.pii.detect_pii", return_value=pii_result):
            tier = classifier.classify("What is the weather today?")
            assert tier == DataTier.SAFE

    def test_never_leave_vault_identity_path(self, classifier):
        tier = classifier.classify("Read the file at vault/identity/MISSION.md")
        assert tier == DataTier.NEVER_LEAVE

    def test_never_leave_telos_mention(self, classifier):
        tier = classifier.classify("Update my TELOS beliefs")
        assert tier == DataTier.NEVER_LEAVE

    def test_never_leave_api_key_pattern(self, classifier):
        tier = classifier.classify("My API key is sk-1234567890abcdef")
        assert tier == DataTier.NEVER_LEAVE

    def test_never_leave_credential_patterns(self, classifier):
        tier = classifier.classify("password: hunter2")
        assert tier == DataTier.NEVER_LEAVE

    def test_sensitive_pii_detected(self, classifier):
        pii_result = PIIResult(
            has_pii=True,
            entities=[PIIEntity(entity_type="PERSON", text="John", start=0, end=4, score=0.9)],
        )
        with patch("core.safety.pii.detect_pii", return_value=pii_result):
            tier = classifier.classify("Tell John about the project")
            assert tier == DataTier.SENSITIVE

    def test_safe_no_pii_no_identity(self, classifier):
        pii_result = PIIResult(has_pii=False, entities=[])
        with patch("core.safety.pii.detect_pii", return_value=pii_result):
            tier = classifier.classify("Explain quantum computing")
            assert tier == DataTier.SAFE


class TestAnonymize:
    def test_anonymize_returns_map(self, classifier):
        pii_result = PIIResult(
            has_pii=True,
            entities=[PIIEntity(entity_type="PERSON", text="Alice", start=5, end=11, score=0.9)],
            scrubbed_text="Tell <PERSON_1> about the project",
            anonymization_map={"<PERSON_1>": "Alice"},
        )
        with patch("core.safety.pii.scrub_pii", return_value=pii_result):
            anon_text, anon_map = classifier.anonymize("Tell Alice about the project")
            assert "<PERSON_1>" in anon_text
            assert anon_map["<PERSON_1>"] == "Alice"

    def test_anonymize_no_pii_returns_original(self, classifier):
        pii_result = PIIResult(has_pii=False, entities=[])
        with patch("core.safety.pii.scrub_pii", return_value=pii_result):
            anon_text, anon_map = classifier.anonymize("Hello world")
            assert anon_text == "Hello world"
            assert anon_map == {}


class TestDeanonymize:
    def test_deanonymize_round_trip(self, classifier):
        anon_map = {"<PERSON_1>": "Alice", "<EMAIL_1>": "a@b.com"}
        text = "Hello <PERSON_1>, your email is <EMAIL_1>"
        result = classifier.deanonymize(text, anon_map)
        assert result == "Hello Alice, your email is a@b.com"

    def test_deanonymize_empty_map(self, classifier):
        result = classifier.deanonymize("Hello world", {})
        assert result == "Hello world"


class TestNeverLeaveHardcoded:
    def test_never_leave_not_configurable(self, classifier):
        tier = classifier.classify("What's in vault/identity/BELIEFS.md?")
        assert tier == DataTier.NEVER_LEAVE
