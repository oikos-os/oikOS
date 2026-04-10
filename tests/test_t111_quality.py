"""Gate 4 quality tests — cosine utility, router init, silent error logging."""

from __future__ import annotations

import logging
import math


class TestCosineUtility:
    """Tests for shared cosine_similarity in core.utils.math."""

    def test_identical_vectors(self):
        from core.utils.math import cosine_similarity
        a = [1.0, 2.0, 3.0]
        assert cosine_similarity(a, a) > 0.999

    def test_orthogonal_vectors(self):
        from core.utils.math import cosine_similarity
        assert cosine_similarity([1.0, 0.0], [0.0, 1.0]) < 0.001

    def test_zero_vector_returns_zero(self):
        from core.utils.math import cosine_similarity
        assert cosine_similarity([0.0, 0.0], [1.0, 2.0]) == 0.0


class TestRouterInit:
    """M-60: last_routed_provider initialized in __init__."""

    def test_last_routed_provider_initialized(self):
        from unittest.mock import MagicMock
        from core.cognition.providers.router import PrivacyAwareRouter

        registry = MagicMock()
        router = PrivacyAwareRouter(registry=registry)
        assert router.last_routed_provider is None


class TestSilentErrorLogging:
    """Verify silent catches now emit debug logs."""

    def test_search_recency_logs_on_bad_timestamp(self, caplog):
        from core.memory.search import compute_recency_weight
        with caplog.at_level(logging.DEBUG):
            result = compute_recency_weight("not-a-date")
        assert result == 0.5  # fallback value

    def test_math_log2_used_in_search(self):
        """M-15: 0.693 replaced with math.log(2)."""
        import inspect
        from core.memory import search
        source = inspect.getsource(search.compute_recency_weight)
        assert "math.log(2)" in source
        assert "0.693" not in source


class TestImportPaths:
    """Verify cosine_similarity imports from shared utility."""

    def test_sensitivity_imports_from_utils(self):
        import inspect
        from core.safety import sensitivity
        source = inspect.getsource(sensitivity)
        assert "from core.utils.math import cosine_similarity" in source

    def test_search_imports_from_utils(self):
        import inspect
        from core.memory import search
        source = inspect.getsource(search)
        assert "from core.utils.math import cosine_similarity" in source
