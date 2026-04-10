"""Tests for cosine sensitivity gate."""

import math
from unittest.mock import patch

from core.safety.sensitivity import (
    check_sovereign_similarity,
    cosine_similarity,
    get_sovereign_entities,
    invalidate_centroid_cache,
    invalidate_entity_cache,
)


# ── cosine_similarity ────────────────────────────────────────────────


def test_cosine_identical_vectors():
    v = [1.0, 2.0, 3.0]
    assert cosine_similarity(v, v) > 0.999


def test_cosine_orthogonal_vectors():
    a = [1.0, 0.0]
    b = [0.0, 1.0]
    assert abs(cosine_similarity(a, b)) < 0.001


def test_cosine_opposite_vectors():
    a = [1.0, 0.0]
    b = [-1.0, 0.0]
    assert cosine_similarity(a, b) < -0.999


def test_cosine_zero_vector():
    assert cosine_similarity([0.0, 0.0], [1.0, 1.0]) == 0.0


# ── check_sovereign_similarity ───────────────────────────────────────


def test_sovereign_similarity_above_threshold():
    """Query vector close to centroid → force local."""
    invalidate_centroid_cache()
    centroid = [1.0, 0.0, 0.0]
    query_vec = [0.95, 0.1, 0.05]  # very close

    with patch("core.safety.sensitivity.get_identity_centroid", return_value=centroid):
        with patch("core.safety.sensitivity.get_sovereign_entities", return_value=set()):
            result = check_sovereign_similarity(query_vec, "what are my goals")

    assert result is True


def test_sovereign_similarity_below_threshold():
    """Query vector far from centroid → don't force local."""
    invalidate_centroid_cache()
    centroid = [1.0, 0.0, 0.0]
    query_vec = [0.0, 1.0, 0.0]  # orthogonal

    with patch("core.safety.sensitivity.get_identity_centroid", return_value=centroid):
        with patch("core.safety.sensitivity.get_sovereign_entities", return_value=set()):
            result = check_sovereign_similarity(query_vec, "explain quantum computing")

    assert result is False


def test_sovereign_similarity_no_centroid():
    """No centroid available → degrade gracefully (return False)."""
    invalidate_centroid_cache()
    with patch("core.safety.sensitivity.get_identity_centroid", return_value=None):
        result = check_sovereign_similarity([1.0, 0.0], "anything")

    assert result is False


def test_sovereign_similarity_entity_lowers_threshold():
    """Entity detected in query → lower threshold → borderline query triggers."""
    invalidate_centroid_cache()
    centroid = [1.0, 0.0, 0.0]
    # Borderline vector: close-ish but below default 0.75 threshold
    query_vec = [0.7, 0.7, 0.14]  # cosine ≈ 0.7 with centroid

    with patch("core.safety.sensitivity.get_identity_centroid", return_value=centroid):
        # Without entity: should NOT trigger (0.7 < 0.75)
        with patch("core.safety.sensitivity.get_sovereign_entities", return_value=set()):
            result_no_entity = check_sovereign_similarity(query_vec, "how is the project going")

        # With entity: should trigger (0.7 >= 0.75 - 0.15 = 0.60)
        with patch("core.safety.sensitivity.get_sovereign_entities", return_value={"the project"}):
            result_with_entity = check_sovereign_similarity(query_vec, "how is the project going")

    assert result_no_entity is False
    assert result_with_entity is True


# ── get_sovereign_entities ───────────────────────────────────────────


def test_sovereign_entities_from_projects(tmp_path):
    """Extracts project names from PROJECTS.md headers."""
    invalidate_entity_cache()
    identity_dir = tmp_path / "identity"
    identity_dir.mkdir()

    projects = identity_dir / "PROJECTS.md"
    projects.write_text("# Active Projects\n## Trendy Decay\n## OIKOS OMEGA\n", encoding="utf-8")

    with patch("core.safety.sensitivity.VAULT_DIR", tmp_path):
        entities = get_sovereign_entities()

    assert "trendy decay" in entities
    assert "oikos omega" in entities
    invalidate_entity_cache()


def test_sovereign_entities_missing_files():
    """No TELOS files → empty set (no crash)."""
    invalidate_entity_cache()
    with patch("core.safety.sensitivity.VAULT_DIR", __import__("pathlib").Path("/nonexistent")):
        entities = get_sovereign_entities()

    assert isinstance(entities, set)
    invalidate_entity_cache()
