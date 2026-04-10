"""Tests for vault dedup checker."""

import pytest
from unittest.mock import patch, MagicMock
from core.agency.research.dedup import is_duplicate


class TestDedup:
    def test_no_match_returns_false(self):
        mock_result = MagicMock()
        mock_result.final_score = 0.3
        with patch("core.agency.research.dedup.hybrid_search", return_value=[mock_result]):
            assert is_duplicate("novel topic") is False

    def test_high_score_returns_true(self):
        mock_result = MagicMock()
        mock_result.final_score = 0.92
        with patch("core.agency.research.dedup.hybrid_search", return_value=[mock_result]):
            assert is_duplicate("existing topic") is True

    def test_threshold_boundary_below(self):
        mock_result = MagicMock()
        mock_result.final_score = 0.84
        with patch("core.agency.research.dedup.hybrid_search", return_value=[mock_result]):
            assert is_duplicate("borderline topic") is False

    def test_threshold_boundary_at(self):
        mock_result = MagicMock()
        mock_result.final_score = 0.85
        with patch("core.agency.research.dedup.hybrid_search", return_value=[mock_result]):
            assert is_duplicate("exact threshold") is True

    def test_no_results_returns_false(self):
        with patch("core.agency.research.dedup.hybrid_search", return_value=[]):
            assert is_duplicate("unique topic") is False

    def test_custom_threshold(self):
        mock_result = MagicMock()
        mock_result.final_score = 0.70
        with patch("core.agency.research.dedup.hybrid_search", return_value=[mock_result]):
            assert is_duplicate("topic", threshold=0.65) is True
            assert is_duplicate("topic", threshold=0.75) is False
