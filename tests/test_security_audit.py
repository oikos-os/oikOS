"""Security tests for audit findings CRIT-001..004, HIGH-001..010."""

from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from core.interface.api.server import create_app


@pytest.fixture
def client():
    return TestClient(create_app())


# ── CRIT-001: Path traversal in SPA ──────────────────────────────────

def test_spa_path_traversal_blocked(client):
    """CRIT-001: ../../etc/passwd must not serve files outside dist/."""
    resp = client.get("/../../etc/passwd")
    # Should get index.html (SPA fallback) or 404, never the actual file
    assert resp.status_code in (200, 404, 307, 308)
    if resp.status_code == 200:
        assert "passwd" not in resp.text or "<!DOCTYPE" in resp.text


def test_spa_path_traversal_auth_toml(client):
    """CRIT-001: traversal to auth config must be blocked."""
    resp = client.get("/../../core/auth/config/auth_headers.toml")
    assert resp.status_code in (200, 404, 307, 308)
    if resp.status_code == 200:
        assert "client-id" not in resp.text


# ── CRIT-002: No private token import ────────────────────────────────

def test_google_status_no_private_import():
    """CRIT-002: auth route must not import _google_tokens directly."""
    import inspect
    from core.interface.api.routes import auth

    source = inspect.getsource(auth.google_status)
    assert "_google_tokens" not in source


# ── CRIT-003: Search error masking ───────────────────────────────────

@patch("core.memory.search.hybrid_search", side_effect=RuntimeError("LanceDB: D:\\secret\\path\\db"))
def test_search_error_masked(mock_search, client):
    """CRIT-003: search errors must not leak internal details."""
    resp = client.get("/api/search?q=test", headers={"X-API-Key": "test"})
    data = resp.json()
    assert "error" in data
    assert "D:\\" not in data["error"]
    assert "LanceDB" not in data["error"]
    assert data["error"] == "Search unavailable"


# ── CRIT-004: Auth error masking ─────────────────────────────────────

@patch("core.auth.google_oauth.get_authorization_url", side_effect=ValueError("GOOGLE_CLIENT_ID not set"))
def test_auth_error_masked(mock_url, client):
    """CRIT-004: auth error must not leak env variable names."""
    resp = client.get("/api/auth/google/connect", headers={"X-API-Key": "test"}, follow_redirects=False)
    assert resp.status_code == 500
    assert "GOOGLE_CLIENT_ID" not in resp.text
    assert "OAuth configuration unavailable" in resp.text


# ── HIGH-001: _safe_msg strips paths/URLs ────────────────────────────

def test_safe_msg_strips_paths():
    """HIGH-001: _safe_msg must strip Windows paths."""
    from core.framework.middleware.error_handler import _safe_msg

    exc = ValueError("File not found: D:\\Development\\OIKOS_OMEGA\\vault\\secret.md")
    result = _safe_msg(exc)
    assert "D:\\" not in result
    assert "[path]" in result


def test_safe_msg_strips_urls():
    """HIGH-001: _safe_msg must strip URLs."""
    from core.framework.middleware.error_handler import _safe_msg

    exc = ValueError("Failed to connect to https://api.secret.com/v1/tokens")
    result = _safe_msg(exc)
    assert "https://" not in result
    assert "[url]" in result


# ── HIGH-002: Approval arg sanitization ──────────────────────────────

def test_summarize_args_redacts_paths():
    """HIGH-002: _summarize_args must redact path-type arguments."""
    from core.framework.middleware.error_handler import _summarize_args

    result = _summarize_args({"path": "/etc/passwd", "content": "hello"})
    assert "/etc/passwd" not in result
    assert "[redacted]" in result


# ── HIGH-003: exec_tools resolved-path check ─────────────────────────

def test_exec_tools_blocks_sacred_boundary():
    """HIGH-003: exec_tools must block commands targeting OIKOS_OMEGA."""
    from core.framework.tools.exec_tools import _check_prohibited_command

    with pytest.raises(PermissionError, match="sacred boundary"):
        _check_prohibited_command("cat D:/Development/OIKOS_OMEGA/core/auth/config/auth_headers.toml")


def test_exec_tools_blocks_traversal_bypass():
    """HIGH-003: exec_tools must catch ./.. path normalization."""
    from core.framework.tools.exec_tools import _check_prohibited_command

    with pytest.raises(PermissionError, match="sacred boundary"):
        _check_prohibited_command("cat D:/Development/./OIKOS_OMEGA/secrets.env")


def test_exec_tools_blocks_destructive():
    """HIGH-003: exec_tools blocks destructive patterns."""
    from core.framework.tools.exec_tools import _check_prohibited_command

    with pytest.raises(PermissionError, match="destructive"):
        _check_prohibited_command("rm -rf /")


# ── HIGH-004: Public health endpoint ─────────────────────────────────

def test_health_public_minimal(client):
    """HIGH-004: /api/health returns only status ok, no internals."""
    resp = client.get("/api/health")
    data = resp.json()
    assert data == {"status": "ok"}
    assert "daemon" not in data
    assert "ollama" not in data


# ── HIGH-005: Jobs dict bounded ──────────────────────────────────────

def test_jobs_eviction():
    """HIGH-005: stale jobs are evicted."""
    from core.interface.api.routes.agents import _jobs, _evict_stale_jobs

    _jobs.clear()
    # Add a stale job
    _jobs["old"] = {"status": "completed", "created": time.time() - 7200}
    _evict_stale_jobs()
    assert "old" not in _jobs


# ── HIGH-007: Upload extension validation ────────────────────────────

def test_upload_rejects_no_extension(client):
    """HIGH-007: files without extensions return 400."""
    from io import BytesIO

    resp = client.post(
        "/api/upload",
        files={"file": ("noext", BytesIO(b"test"), "application/octet-stream")},
        headers={"X-API-Key": "test"},
    )
    assert resp.status_code == 400


def test_upload_rejects_bad_extension(client):
    """HIGH-007: disallowed extensions return 400."""
    from io import BytesIO

    resp = client.post(
        "/api/upload",
        files={"file": ("evil.exe", BytesIO(b"test"), "application/octet-stream")},
        headers={"X-API-Key": "test"},
    )
    assert resp.status_code == 400


# ── HIGH-008: Onboarding test endpoint locked ────────────────────────

@patch("core.onboarding.state.is_onboarding_complete", return_value=True)
def test_onboarding_test_locked_after_complete(mock_complete, client):
    """HIGH-008: /providers/test returns 403 after onboarding complete."""
    resp = client.post(
        "/api/onboarding/providers/test",
        json={"provider": "anthropic", "api_key": "sk-test"},
    )
    assert resp.status_code == 403


# ── HIGH-009/010: Generic error messages ─────────────────────────────

def test_system_tools_no_exception_leak():
    """HIGH-010: system tools must not return raw exception strings."""
    from core.framework.tools.system_tools import daemon_start

    with patch("core.autonomic.daemon.start", side_effect=RuntimeError("bind: D:\\path\\to\\socket")):
        result = daemon_start()
        assert result["status"] == "error"
        assert "D:\\" not in result["message"]
        assert result["message"] == "Daemon failed to start"


# ── MED-078: Personal docs removed ──────────────────────────────────

def test_personal_docs_not_in_repo():
    """MED-078: memory/purgatory/converted/ must not exist."""
    path = Path(__file__).parent.parent / "memory" / "purgatory" / "converted"
    assert not path.exists(), f"Personal docs still present at {path}"


# ── MED-079: Docker volume scoped ───────────────────────────────────

def test_docker_volume_scoped():
    """MED-079: docker-compose must not mount all of ./memory."""
    compose = Path(__file__).parent.parent / "docker-compose.yml"
    content = compose.read_text(encoding="utf-8")
    assert "./memory:/app/memory" not in content
    assert "./memory/vault:/app/memory/vault" in content
