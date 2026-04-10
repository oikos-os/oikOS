"""Root-level test fixtures.

Loads a tracked owner_identity fixture so PII defense modules have a
known configuration during tests, independent of any per-developer
``config/owner_identity.toml`` that may or may not exist.
"""

from __future__ import annotations

import os
from pathlib import Path

_FIXTURE_PATH = Path(__file__).parent / "fixtures" / "test_owner_identity.toml"


def pytest_configure(config):  # noqa: ARG001 — pytest hook signature
    """Point the owner_identity loader at the test fixture before import."""
    os.environ.setdefault("OIKOS_OWNER_IDENTITY_PATH", str(_FIXTURE_PATH))
    # Reset any cached load from prior processes or in-process imports.
    try:
        from core.interface.owner_identity import reset_cache
        reset_cache()
    except ImportError:
        pass
