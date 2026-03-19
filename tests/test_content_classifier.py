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


class TestCredentialPatterns:
    """Phase 7f Module 3 — expanded credential detection."""

    def test_anthropic_api_key(self, classifier):
        tier = classifier.classify("key is sk-ant-api03-abc123def456ghi789jkl012mno345")
        assert tier == DataTier.NEVER_LEAVE

    def test_openai_project_key(self, classifier):
        tier = classifier.classify("OPENAI_KEY=sk-proj-abcdefghij1234567890")
        assert tier == DataTier.NEVER_LEAVE

    def test_github_pat(self, classifier):
        tier = classifier.classify("token: ghp_" + "a" * 36)
        assert tier == DataTier.NEVER_LEAVE

    def test_github_oauth(self, classifier):
        tier = classifier.classify("oauth: gho_" + "b" * 36)
        assert tier == DataTier.NEVER_LEAVE

    def test_github_app_token(self, classifier):
        tier = classifier.classify("install: ghs_" + "c" * 36)
        assert tier == DataTier.NEVER_LEAVE

    def test_gitlab_pat(self, classifier):
        tier = classifier.classify("GL_TOKEN=glpat-abcdefghij1234567890")
        assert tier == DataTier.NEVER_LEAVE

    def test_slack_bot_token(self, classifier):
        tier = classifier.classify("SLACK=xoxb-123456789-abcdefghij")
        assert tier == DataTier.NEVER_LEAVE

    def test_sendgrid_key(self, classifier):
        tier = classifier.classify("SG." + "a" * 22 + "." + "b" * 43)
        assert tier == DataTier.NEVER_LEAVE

    def test_aws_key_still_works(self, classifier):
        tier = classifier.classify("AWS_KEY=AKIAIOSFODNN7EXAMPLE")
        assert tier == DataTier.NEVER_LEAVE

    def test_pem_key_still_works(self, classifier):
        tier = classifier.classify("-----BEGIN RSA PRIVATE KEY-----")
        assert tier == DataTier.NEVER_LEAVE

    def test_jwt_still_works(self, classifier):
        tier = classifier.classify("eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0")
        assert tier == DataTier.NEVER_LEAVE


class TestEntropyDetection:
    """High-entropy token detection for unknown credential formats."""

    def test_random_base64_string_blocked(self, classifier):
        # Simulates an unknown API key format — high entropy, 40+ chars
        import string, random
        random.seed(42)
        token = "".join(random.choices(string.ascii_letters + string.digits, k=40))
        pii_result = PIIResult(has_pii=False, entities=[])
        with patch("core.safety.pii.detect_pii", return_value=pii_result):
            tier = classifier.classify(f"secret token: {token}")
        assert tier == DataTier.NEVER_LEAVE

    def test_normal_english_not_blocked(self, classifier):
        pii_result = PIIResult(has_pii=False, entities=[])
        with patch("core.safety.pii.detect_pii", return_value=pii_result):
            tier = classifier.classify("This is a normal English sentence about programming")
        assert tier == DataTier.SAFE

    def test_url_not_false_positive(self, classifier):
        pii_result = PIIResult(has_pii=False, entities=[])
        with patch("core.safety.pii.detect_pii", return_value=pii_result):
            tier = classifier.classify("Visit https://example.com/very-long-path-segment-here-for-testing")
        assert tier == DataTier.SAFE

    def test_short_tokens_not_blocked(self, classifier):
        pii_result = PIIResult(has_pii=False, entities=[])
        with patch("core.safety.pii.detect_pii", return_value=pii_result):
            tier = classifier.classify("code: abc123")
        assert tier == DataTier.SAFE
