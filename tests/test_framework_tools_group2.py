"""Tests for Group 2 MCP tools: vault_ingest, vault_stats, git_status, git_log,
daemon_start/stop, config_get/set, notify, oracle_status."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch, mock_open

import pytest


# ── Helpers ──────────────────────────────────────────────────────────────────

VALID_FRONTMATTER = "---\ntier: semantic\ndomain: GENERAL\nstatus: active\nupdated: 2026-01-01\n---\n\n# Content"
MISSING_FIELD_FM = "---\ntier: semantic\ndomain: GENERAL\n---\n\n# Missing status + updated"
NO_FM = "# Just a heading\n\nNo frontmatter here."


# ── vault_ingest ─────────────────────────────────────────────────────────────

class TestVaultIngest:
    def _call(self, source_path, tmp_path, vault_tier="semantic", domain="GENERAL"):
        from core.framework.tools.vault_tools import vault_ingest
        allowed = {str(tmp_path): "READ"}
        with patch("core.interface.config.FILE_AGENT_ALLOWED_PATHS", allowed), \
             patch("core.agency.file_agent._PROHIBITED_PATHS_DEFAULT", []):
            return vault_ingest(source_path, vault_tier=vault_tier, domain=domain)

    def test_missing_source_returns_error(self, tmp_path):
        result = self._call(str(tmp_path / "nonexistent.md"), tmp_path)
        assert result["status"] == "error"
        assert "not found" in result["message"].lower()

    def test_source_is_directory_returns_error(self, tmp_path):
        result = self._call(str(tmp_path), tmp_path)
        assert result["status"] == "error"
        assert "not a file" in result["message"].lower()

    def test_no_frontmatter_returns_error(self, tmp_path):
        f = tmp_path / "no_fm.md"
        f.write_text(NO_FM)
        result = self._call(str(f), tmp_path)
        assert result["status"] == "error"
        assert "frontmatter" in result["message"].lower()
        assert "required_fields" in result

    def test_missing_frontmatter_fields_returns_error(self, tmp_path):
        f = tmp_path / "partial_fm.md"
        f.write_text(MISSING_FIELD_FM)
        result = self._call(str(f), tmp_path)
        assert result["status"] == "error"
        assert "missing" in result["message"].lower()
        missing = set(result["required_fields"])
        assert "status" in missing or "updated" in missing

    def test_invalid_tier_returns_error(self, tmp_path):
        f = tmp_path / "good.md"
        f.write_text(VALID_FRONTMATTER)
        result = self._call(str(f), tmp_path, vault_tier="invalid_tier")
        assert result["status"] == "error"
        assert "vault_tier" in result["message"]

    def test_valid_file_creates_proposal(self, tmp_path):
        f = tmp_path / "good.md"
        f.write_text(VALID_FRONTMATTER)
        mock_proposal = MagicMock()
        mock_proposal.proposal_id = "abc123"
        with patch("core.agency.approval.ApprovalQueue") as MockQueue:
            MockQueue.return_value.propose.return_value = mock_proposal
            result = self._call(str(f), tmp_path)
        assert result["status"] == "proposal_created"
        assert "proposal_id" in result
        assert result["tier"] == "semantic"
        assert result["domain"] == "GENERAL"

    def test_prohibited_source_blocked(self, tmp_path):
        """Scope validation blocks reads from prohibited paths."""
        from core.framework.tools.vault_tools import vault_ingest
        result = vault_ingest("D:/Development/OIKOS_OMEGA/core/safety/pii.py")
        assert result["status"] == "error"
        assert "PROHIBITED" in result["message"] or "outside" in result["message"].lower()

    def test_out_of_scope_source_blocked(self, tmp_path):
        """Scope validation blocks reads from paths not in allowed scope."""
        from core.framework.tools.vault_tools import vault_ingest
        result = vault_ingest("C:/Users/arodr/.ssh/id_rsa")
        assert result["status"] == "error"
        assert "outside" in result["message"].lower() or "scope" in result["message"].lower()


# ── vault_stats ──────────────────────────────────────────────────────────────

class TestVaultStats:
    def test_returns_expected_keys(self):
        from core.framework.tools.vault_tools import vault_stats
        with patch("core.interface.config.VAULT_DIR") as mock_vault, \
             patch("core.interface.config.LANCEDB_DIR") as mock_lancedb:
            # Make tier dirs not exist so we get empty counts
            mock_vault.__truediv__ = lambda self, other: MagicMock(exists=lambda: False)
            mock_lancedb.exists.return_value = False
            result = vault_stats()
        assert "total_files" in result
        assert "by_tier" in result
        assert "stale_files" in result
        assert "orphan_files" in result
        assert "index_tables" in result

    def test_counts_files_per_tier(self, tmp_path):
        import core.interface.config as cfg
        import core.framework.tools.vault_tools as vt

        identity = tmp_path / "identity"
        knowledge = tmp_path / "knowledge"
        patterns = tmp_path / "patterns"
        identity.mkdir(); knowledge.mkdir(); patterns.mkdir()

        for i in range(2):
            (identity / f"file{i}.md").write_text(VALID_FRONTMATTER)
        (knowledge / "one.md").write_text(VALID_FRONTMATTER)

        orig_vault = cfg.VAULT_DIR
        orig_lancedb = cfg.LANCEDB_DIR
        try:
            cfg.VAULT_DIR = tmp_path
            cfg.LANCEDB_DIR = tmp_path / "lancedb"
            result = vt.vault_stats()
        finally:
            cfg.VAULT_DIR = orig_vault
            cfg.LANCEDB_DIR = orig_lancedb

        assert result["by_tier"]["core"] == 2
        assert result["by_tier"]["semantic"] == 1
        assert result["by_tier"]["procedural"] == 0
        assert result["total_files"] == 3

    def test_detects_orphan_files(self, tmp_path):
        import core.interface.config as cfg
        import core.framework.tools.vault_tools as vt

        identity = tmp_path / "identity"
        identity.mkdir()
        (identity / "orphan.md").write_text(NO_FM)

        orig_vault = cfg.VAULT_DIR
        orig_lancedb = cfg.LANCEDB_DIR
        try:
            cfg.VAULT_DIR = tmp_path
            cfg.LANCEDB_DIR = tmp_path / "lancedb"
            result = vt.vault_stats()
        finally:
            cfg.VAULT_DIR = orig_vault
            cfg.LANCEDB_DIR = orig_lancedb

        assert len(result["orphan_files"]) == 1


# ── git_status ────────────────────────────────────────────────────────────────

class TestGitStatus:
    def _call(self, repo_path):
        from core.framework.tools.git_tools import git_status
        return git_status(repo_path)

    def test_scope_violation_returns_error(self):
        result = self._call("C:/Windows/System32")
        assert result["status"] == "error"
        assert "scope" in result["message"].lower() or "allowed" in result["message"].lower()

    def test_valid_scope_returns_dict(self):
        mock_porcelain = " M file.py\n?? new.txt\n"
        mock_branch = "main\n"

        with patch("core.framework.tools.git_tools._validate_repo_scope") as mock_scope, \
             patch("core.framework.tools.git_tools._run_git") as mock_git:
            mock_scope.return_value = Path("D:/COMMAND")
            mock_git.side_effect = [mock_porcelain, mock_branch]
            result = self._call("D:/COMMAND")

        assert result["branch"] == "main"
        assert not result["clean"]
        assert "new.txt" in result["untracked"]
        assert "file.py" in result["modified"]

    def test_clean_repo(self):
        with patch("core.framework.tools.git_tools._validate_repo_scope") as mock_scope, \
             patch("core.framework.tools.git_tools._run_git") as mock_git:
            mock_scope.return_value = Path("D:/COMMAND")
            mock_git.side_effect = ["", "master\n"]
            result = self._call("D:/COMMAND")

        assert result["clean"] is True
        assert result["staged"] == []
        assert result["modified"] == []
        assert result["untracked"] == []

    def test_staged_files_detected(self):
        with patch("core.framework.tools.git_tools._validate_repo_scope") as mock_scope, \
             patch("core.framework.tools.git_tools._run_git") as mock_git:
            mock_scope.return_value = Path("D:/COMMAND")
            mock_git.side_effect = ["A  staged.py\n", "feature\n"]
            result = self._call("D:/COMMAND")

        assert "staged.py" in result["staged"]
        assert result["clean"] is False

    def test_git_error_returns_error_dict(self):
        with patch("core.framework.tools.git_tools._validate_repo_scope") as mock_scope, \
             patch("core.framework.tools.git_tools._run_git") as mock_git:
            mock_scope.return_value = Path("D:/COMMAND")
            mock_git.side_effect = RuntimeError("not a git repository")
            result = self._call("D:/COMMAND")

        assert result["status"] == "error"


# ── git_log ───────────────────────────────────────────────────────────────────

class TestGitLog:
    def _call(self, repo_path, count=10):
        from core.framework.tools.git_tools import git_log
        return git_log(repo_path, count=count)

    def test_scope_violation_returns_error_list(self):
        result = self._call("C:/Windows/System32")
        assert isinstance(result, list)
        assert result[0]["status"] == "error"

    def test_returns_parsed_commits(self):
        raw = "abc123|Alice|2026-01-01T00:00:00Z|feat: add thing\ndef456|Bob|2026-01-02T00:00:00Z|fix: bug\n"
        with patch("core.framework.tools.git_tools._validate_repo_scope") as mock_scope, \
             patch("core.framework.tools.git_tools._run_git") as mock_git:
            mock_scope.return_value = Path("D:/COMMAND")
            mock_git.return_value = raw
            result = self._call("D:/COMMAND", count=5)

        assert len(result) == 2
        assert result[0]["hash"] == "abc123"
        assert result[0]["message"] == "feat: add thing"
        assert result[1]["author"] == "Bob"

    def test_count_capped_at_50(self):
        with patch("core.framework.tools.git_tools._validate_repo_scope") as mock_scope, \
             patch("core.framework.tools.git_tools._run_git") as mock_git:
            mock_scope.return_value = Path("D:/COMMAND")
            mock_git.return_value = ""
            self._call("D:/COMMAND", count=999)
            call_args = mock_git.call_args[0]
            # find --max-count arg
            assert any("50" in str(a) for a in call_args)


# ── daemon_start / daemon_stop ────────────────────────────────────────────────

class TestDaemon:
    def test_daemon_start_success(self):
        from core.framework.tools.system_tools import daemon_start
        with patch("core.autonomic.daemon.start") as mock_start:
            result = daemon_start()
        assert result["status"] == "started"
        mock_start.assert_called_once()

    def test_daemon_start_error(self):
        from core.framework.tools.system_tools import daemon_start
        with patch("core.autonomic.daemon.start", side_effect=RuntimeError("already running")):
            result = daemon_start()
        assert result["status"] == "error"
        assert "already running" in result["message"]

    def test_daemon_stop_success(self):
        from core.framework.tools.system_tools import daemon_stop
        with patch("core.autonomic.daemon.stop") as mock_stop:
            result = daemon_stop()
        assert result["status"] == "stopped"
        mock_stop.assert_called_once()

    def test_daemon_stop_error(self):
        from core.framework.tools.system_tools import daemon_stop
        with patch("core.autonomic.daemon.stop", side_effect=RuntimeError("not running")):
            result = daemon_stop()
        assert result["status"] == "error"


# ── config_get ────────────────────────────────────────────────────────────────

class TestConfigGet:
    def test_reads_settings_key(self, tmp_path):
        from core.framework.tools.system_tools import config_get
        settings = tmp_path / "settings.json"
        settings.write_text('{"inference_temperature": 0.8}')
        with patch("core.interface.config.PROJECT_ROOT", tmp_path):
            result = config_get("inference_temperature")
        assert result["value"] == 0.8
        assert result["key"] == "inference_temperature"

    def test_redacts_secret_key(self, tmp_path):
        from core.framework.tools.system_tools import config_get
        settings = tmp_path / "settings.json"
        settings.write_text('{"api_key": "sk-secret-value"}')
        with patch("core.interface.config.PROJECT_ROOT", tmp_path):
            result = config_get("api_key")
        assert result["value"] == "[REDACTED]"

    def test_not_found_returns_status(self, tmp_path):
        from core.framework.tools.system_tools import config_get
        settings = tmp_path / "settings.json"
        settings.write_text("{}")
        with patch("core.interface.config.PROJECT_ROOT", tmp_path):
            result = config_get("missing_key")
        assert result["status"] == "not_found"

    def test_invalid_source_returns_error(self, tmp_path):
        from core.framework.tools.system_tools import config_get
        with patch("core.interface.config.PROJECT_ROOT", tmp_path):
            result = config_get("anything", source="invalid")
        assert result["status"] == "error"

    def test_missing_settings_file_returns_error(self, tmp_path):
        from core.framework.tools.system_tools import config_get
        with patch("core.interface.config.PROJECT_ROOT", tmp_path):
            result = config_get("key")
        assert result["status"] == "error"


# ── config_set ────────────────────────────────────────────────────────────────

class TestConfigSet:
    def test_set_normal_key(self, tmp_path):
        from core.framework.tools.system_tools import config_set
        settings = tmp_path / "settings.json"
        settings.write_text("{}")
        with patch("core.interface.config.PROJECT_ROOT", tmp_path):
            result = config_set("inference_temperature", "0.9")
        assert result["status"] == "updated"
        assert result["key"] == "inference_temperature"
        data = json.loads(settings.read_text())
        assert data["inference_temperature"] == "0.9"

    def test_blocked_secret_key(self, tmp_path):
        from core.framework.tools.system_tools import config_set
        with patch("core.interface.config.PROJECT_ROOT", tmp_path):
            result = config_set("api_token", "some-value")
        assert result["status"] == "refused"
        assert "api_token" in result["message"]

    def test_blocked_password_key(self, tmp_path):
        from core.framework.tools.system_tools import config_set
        with patch("core.interface.config.PROJECT_ROOT", tmp_path):
            result = config_set("db_password", "hunter2")
        assert result["status"] == "refused"

    def test_creates_settings_if_missing(self, tmp_path):
        from core.framework.tools.system_tools import config_set
        with patch("core.interface.config.PROJECT_ROOT", tmp_path):
            result = config_set("new_setting", "value")
        assert result["status"] == "updated"
        data = json.loads((tmp_path / "settings.json").read_text())
        assert data["new_setting"] == "value"


# ── notify ────────────────────────────────────────────────────────────────────

class TestNotify:
    def test_writes_to_notifications_log(self, tmp_path):
        from core.framework.tools.system_tools import notify
        logs_dir = tmp_path / "logs"
        logs_dir.mkdir()
        with patch("core.interface.config.PROJECT_ROOT", tmp_path):
            result = notify("Test Title", "Test message", severity="info")
        assert result["status"] == "sent"
        assert result["title"] == "Test Title"
        log_file = logs_dir / "notifications.jsonl"
        assert log_file.exists()
        entry = json.loads(log_file.read_text().strip())
        assert entry["title"] == "Test Title"
        assert entry["message"] == "Test message"
        assert entry["severity"] == "info"

    def test_appends_multiple_notifications(self, tmp_path):
        from core.framework.tools.system_tools import notify
        logs_dir = tmp_path / "logs"
        logs_dir.mkdir()
        with patch("core.interface.config.PROJECT_ROOT", tmp_path):
            notify("First", "msg1")
            notify("Second", "msg2")
        log_file = logs_dir / "notifications.jsonl"
        lines = log_file.read_text().strip().splitlines()
        assert len(lines) == 2


# ── oracle_status ─────────────────────────────────────────────────────────────

class TestOracleStatus:
    def test_no_agents_found(self):
        from core.framework.tools.oracle_tools import oracle_status
        with patch("core.framework.tools.oracle_tools._AGENT_STATE_PATHS", {}):
            result = oracle_status()
        assert result["status"] == "no agents found"

    def test_missing_state_files_returns_graceful(self, tmp_path):
        from core.framework.tools.oracle_tools import oracle_status
        fake_paths = {
            "tempest": tmp_path / "tempest" / "data" / "state.json",
            "sentinel": tmp_path / "sentinel" / "data" / "state.json",
        }
        with patch("core.framework.tools.oracle_tools._AGENT_STATE_PATHS", fake_paths):
            result = oracle_status()
        assert result["status"] == "no agents found"

    def test_reads_agent_state(self, tmp_path):
        from core.framework.tools.oracle_tools import oracle_status
        state_dir = tmp_path / "tempest" / "data"
        state_dir.mkdir(parents=True)
        state_file = state_dir / "state.json"
        state_file.write_text(json.dumps({
            "last_run": "2026-01-01T00:00:00Z",
            "positions": {"BTC": 0.5},
            "daily_pnl": 42.0,
            "errors": [],
        }))
        sentinel_missing = tmp_path / "sentinel" / "data" / "state.json"
        fake_paths = {"tempest": state_file, "sentinel": sentinel_missing}
        with patch("core.framework.tools.oracle_tools._AGENT_STATE_PATHS", fake_paths):
            result = oracle_status()
        assert result["status"] == "ok"
        assert result["agents"]["tempest"]["status"] == "active"
        assert result["agents"]["tempest"]["daily_pnl"] == 42.0
        assert result["agents"]["sentinel"]["status"] == "not_found"

    def test_invalid_state_json_returns_not_found(self, tmp_path):
        from core.framework.tools.oracle_tools import oracle_status
        state_dir = tmp_path / "agent" / "data"
        state_dir.mkdir(parents=True)
        state_file = state_dir / "state.json"
        state_file.write_text("{ invalid json }")
        fake_paths = {"agent": state_file}
        with patch("core.framework.tools.oracle_tools._AGENT_STATE_PATHS", fake_paths):
            result = oracle_status()
        assert result["status"] == "no agents found"
