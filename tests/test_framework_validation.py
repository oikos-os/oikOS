"""Tests for framework-level input validators."""

import pytest
from core.framework.validation import validate_filename


class TestValidateFilename:
    def test_valid_filename(self):
        assert validate_filename("report.md") == "report.md"

    def test_valid_with_underscores(self):
        assert validate_filename("my_research_2026.md") == "my_research_2026.md"

    def test_path_traversal_rejected(self):
        with pytest.raises(ValueError, match="path"):
            validate_filename("../../etc/passwd")

    def test_absolute_path_rejected(self):
        with pytest.raises(ValueError, match="path"):
            validate_filename("/etc/passwd")

    def test_directory_component_rejected(self):
        with pytest.raises(ValueError, match="path"):
            validate_filename("subdir/file.md")

    def test_backslash_path_rejected(self):
        with pytest.raises(ValueError, match="path"):
            validate_filename("subdir\\file.md")

    def test_empty_rejected(self):
        with pytest.raises(ValueError, match="empty"):
            validate_filename("")

    def test_whitespace_only_rejected(self):
        with pytest.raises(ValueError, match="empty"):
            validate_filename("   ")

    def test_dotdot_in_name_rejected(self):
        with pytest.raises(ValueError, match="traversal"):
            validate_filename("..hidden")
