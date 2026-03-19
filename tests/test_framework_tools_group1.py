"""Tests for T-057 Group 1 Gap-Closer tools: exec, fs_move, fs_copy, fs_delete."""

import subprocess
from unittest.mock import MagicMock, patch

import pytest


# ── Helpers ─────────────────────────────────────────────────────────────────

def _mock_agent():
    agent = MagicMock()
    proposal = MagicMock()
    proposal.proposal_id = "prop-test-001"
    agent.move_file.return_value = proposal
    agent.copy_file.return_value = proposal
    agent.delete_file.return_value = proposal
    return agent, proposal


# ── oikos_system_exec ────────────────────────────────────────────────────────

class TestSystemExec:
    def test_happy_path(self):
        from core.framework.tools.exec_tools import system_exec
        mock_result = MagicMock()
        mock_result.stdout = "hello"
        mock_result.stderr = ""
        mock_result.returncode = 0
        with patch("subprocess.run", return_value=mock_result):
            result = system_exec("echo hello", cwd="D:/COMMAND/staging")
        assert result["stdout"] == "hello"
        assert result["exit_code"] == 0
        assert result["truncated"] is False

    def test_no_cwd(self):
        from core.framework.tools.exec_tools import system_exec
        mock_result = MagicMock()
        mock_result.stdout = "ok"
        mock_result.stderr = ""
        mock_result.returncode = 0
        with patch("subprocess.run", return_value=mock_result):
            result = system_exec("echo ok")
        assert result["exit_code"] == 0

    def test_prohibited_rm_rf(self):
        from core.framework.tools.exec_tools import system_exec
        with pytest.raises(PermissionError, match="PROHIBITED"):
            system_exec("rm -rf /")

    def test_prohibited_format_c(self):
        from core.framework.tools.exec_tools import system_exec
        with pytest.raises(PermissionError, match="PROHIBITED"):
            system_exec("format C: /q")

    def test_prohibited_del_system(self):
        from core.framework.tools.exec_tools import system_exec
        with pytest.raises(PermissionError, match="PROHIBITED"):
            system_exec("del /s /q C:\\Windows")

    def test_prohibited_oikos_omega_path(self):
        from core.framework.tools.exec_tools import system_exec
        with pytest.raises(PermissionError, match="PROHIBITED"):
            system_exec("rm -rf D:/Development/OIKOS_OMEGA")

    def test_scope_violation_cwd(self):
        from core.framework.tools.exec_tools import system_exec
        with pytest.raises(PermissionError):
            system_exec("ls", cwd="C:/Windows/System32")

    def test_oikos_omega_cwd_blocked(self):
        from core.framework.tools.exec_tools import system_exec
        with pytest.raises(PermissionError, match="PROHIBITED"):
            system_exec("ls", cwd="D:/Development/OIKOS_OMEGA/core")

    def test_output_truncation(self):
        from core.framework.tools.exec_tools import system_exec
        big_stdout = "x" * 20_000
        mock_result = MagicMock()
        mock_result.stdout = big_stdout
        mock_result.stderr = ""
        mock_result.returncode = 0
        with patch("subprocess.run", return_value=mock_result):
            result = system_exec("echo big")
        assert result["truncated"] is True
        assert len(result["stdout"]) <= 10_000

    def test_timeout_returns_error(self):
        from core.framework.tools.exec_tools import system_exec
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("cmd", 30)):
            result = system_exec("sleep 999")
        assert result["exit_code"] == -1
        assert "timed out" in result["stderr"]

    def test_stderr_captured(self):
        from core.framework.tools.exec_tools import system_exec
        mock_result = MagicMock()
        mock_result.stdout = ""
        mock_result.stderr = "error message"
        mock_result.returncode = 1
        with patch("subprocess.run", return_value=mock_result):
            result = system_exec("bad_command")
        assert result["stderr"] == "error message"
        assert result["exit_code"] == 1


# ── oikos_fs_move ────────────────────────────────────────────────────────────

class TestFsMove:
    def test_happy_path(self):
        from core.framework.tools.fs_tools import fs_move
        agent, proposal = _mock_agent()
        with patch("core.framework.tools.fs_tools._file_agent", agent):
            result = fs_move(
                "D:/COMMAND/staging/a.txt",
                "D:/COMMAND/messages/a.txt",
                "test move",
            )
        assert result["status"] == "proposal_created"
        assert result["proposal_id"] == "prop-test-001"
        assert result["source"] == "D:/COMMAND/staging/a.txt"
        assert result["destination"] == "D:/COMMAND/messages/a.txt"

    def test_scope_violation_raises(self):
        from core.framework.tools.fs_tools import fs_move
        agent = MagicMock()
        agent.move_file.side_effect = PermissionError("Path outside allowed scope")
        with patch("core.framework.tools.fs_tools._file_agent", agent):
            with pytest.raises(PermissionError):
                fs_move("C:/Windows/file.txt", "D:/COMMAND/staging/file.txt")

    def test_prohibited_path_raises(self):
        from core.framework.tools.fs_tools import fs_move
        agent = MagicMock()
        agent.move_file.side_effect = PermissionError("PROHIBITED")
        with patch("core.framework.tools.fs_tools._file_agent", agent):
            with pytest.raises(PermissionError, match="PROHIBITED"):
                fs_move(
                    "D:/Development/OIKOS_OMEGA/core/x.py",
                    "D:/COMMAND/staging/x.py",
                )

    def test_default_reason(self):
        from core.framework.tools.fs_tools import fs_move
        agent, proposal = _mock_agent()
        with patch("core.framework.tools.fs_tools._file_agent", agent):
            result = fs_move("D:/COMMAND/staging/x.txt", "D:/COMMAND/messages/x.txt")
        assert result["reason"] == "MCP tool move"
        agent.move_file.assert_called_once_with(
            "D:/COMMAND/staging/x.txt",
            "D:/COMMAND/messages/x.txt",
            reason="MCP tool move",
        )


# ── oikos_fs_copy ────────────────────────────────────────────────────────────

class TestFsCopy:
    def test_happy_path(self):
        from core.framework.tools.fs_tools import fs_copy
        agent, proposal = _mock_agent()
        with patch("core.framework.tools.fs_tools._file_agent", agent):
            result = fs_copy(
                "D:/COMMAND/staging/a.txt",
                "D:/COMMAND/messages/a.txt",
                "test copy",
            )
        assert result["status"] == "proposal_created"
        assert result["proposal_id"] == "prop-test-001"
        assert result["source"] == "D:/COMMAND/staging/a.txt"

    def test_scope_violation_raises(self):
        from core.framework.tools.fs_tools import fs_copy
        agent = MagicMock()
        agent.copy_file.side_effect = PermissionError("Path outside allowed scope")
        with patch("core.framework.tools.fs_tools._file_agent", agent):
            with pytest.raises(PermissionError):
                fs_copy("C:/bad/path.txt", "D:/COMMAND/staging/file.txt")

    def test_prohibited_src_raises(self):
        from core.framework.tools.fs_tools import fs_copy
        agent = MagicMock()
        agent.copy_file.side_effect = PermissionError("PROHIBITED")
        with patch("core.framework.tools.fs_tools._file_agent", agent):
            with pytest.raises(PermissionError, match="PROHIBITED"):
                fs_copy(
                    "D:/Development/OIKOS_OMEGA/core/x.py",
                    "D:/COMMAND/staging/x.py",
                )

    def test_default_reason(self):
        from core.framework.tools.fs_tools import fs_copy
        agent, proposal = _mock_agent()
        with patch("core.framework.tools.fs_tools._file_agent", agent):
            result = fs_copy("D:/COMMAND/staging/x.txt", "D:/COMMAND/messages/x.txt")
        assert result["reason"] == "MCP tool copy"


# ── oikos_fs_delete ──────────────────────────────────────────────────────────

class TestFsDelete:
    def test_happy_path(self):
        from core.framework.tools.fs_tools import fs_delete
        agent, proposal = _mock_agent()
        with patch("core.framework.tools.fs_tools._file_agent", agent):
            result = fs_delete("D:/COMMAND/staging/old.txt", "cleanup")
        assert result["status"] == "proposal_created"
        assert result["proposal_id"] == "prop-test-001"
        assert result["path"] == "D:/COMMAND/staging/old.txt"

    def test_vault_path_raises(self):
        from core.framework.tools.fs_tools import fs_delete
        agent = MagicMock()
        agent.delete_file.side_effect = PermissionError("PROHIBITED: delete from read-only scope")
        with patch("core.framework.tools.fs_tools._file_agent", agent):
            with pytest.raises(PermissionError, match="PROHIBITED"):
                fs_delete("D:/SIGMA/Vault/SIGMA_VAULT/important.md")

    def test_prohibited_oikos_omega_raises(self):
        from core.framework.tools.fs_tools import fs_delete
        agent = MagicMock()
        agent.delete_file.side_effect = PermissionError("PROHIBITED")
        with patch("core.framework.tools.fs_tools._file_agent", agent):
            with pytest.raises(PermissionError, match="PROHIBITED"):
                fs_delete("D:/Development/OIKOS_OMEGA/core/important.py")

    def test_scope_violation_raises(self):
        from core.framework.tools.fs_tools import fs_delete
        agent = MagicMock()
        agent.delete_file.side_effect = PermissionError("Path outside allowed scope")
        with patch("core.framework.tools.fs_tools._file_agent", agent):
            with pytest.raises(PermissionError):
                fs_delete("C:/Windows/system32/file.dll")

    def test_default_reason(self):
        from core.framework.tools.fs_tools import fs_delete
        agent, proposal = _mock_agent()
        with patch("core.framework.tools.fs_tools._file_agent", agent):
            result = fs_delete("D:/COMMAND/staging/x.txt")
        assert result["reason"] == "MCP tool delete"


# ── FileAgent: copy_file and delete_file unit tests ─────────────────────────

class TestFileAgentCopy:
    def _make_agent(self, allowed=None, prohibited=None):
        from core.agency.file_agent import FileAgent
        matrix = MagicMock()
        queue = MagicMock()
        proposal = MagicMock()
        proposal.proposal_id = "copy-001"
        queue.propose.return_value = proposal
        if allowed is None:
            allowed = {
                "D:/COMMAND/staging": "READ_WRITE",
                "D:/COMMAND/messages": "READ_WRITE",
            }
        return FileAgent(matrix, queue, allowed_paths=allowed, prohibited_paths=prohibited or [])

    def test_copy_file_creates_proposal(self, tmp_path):
        src = tmp_path / "src.txt"
        src.write_text("hello")
        dst = tmp_path / "dst.txt"
        agent = self._make_agent(allowed={str(tmp_path): "READ_WRITE"})
        proposal = agent.copy_file(str(src), str(dst), "test copy")
        assert proposal.proposal_id == "copy-001"

    def test_copy_file_src_not_found(self, tmp_path):
        agent = self._make_agent(allowed={str(tmp_path): "READ_WRITE"})
        with pytest.raises(FileNotFoundError):
            agent.copy_file(str(tmp_path / "missing.txt"), str(tmp_path / "dst.txt"), "x")

    def test_execute_approved_copy(self, tmp_path):
        import shutil
        src = tmp_path / "src.txt"
        src.write_text("content")
        dst = tmp_path / "dst.txt"
        agent = self._make_agent(allowed={str(tmp_path): "READ_WRITE"})
        proposal = MagicMock()
        proposal.status = "approved"
        proposal.proposal_id = "copy-001"
        proposal.tool_args = {"src": str(src), "dst": str(dst)}
        agent.execute_approved_copy(proposal)
        assert dst.read_text() == "content"


class TestFileAgentDelete:
    def _make_agent(self, allowed=None, prohibited=None):
        from core.agency.file_agent import FileAgent
        matrix = MagicMock()
        queue = MagicMock()
        proposal = MagicMock()
        proposal.proposal_id = "del-001"
        queue.propose.return_value = proposal
        if allowed is None:
            allowed = {"D:/COMMAND/staging": "READ_WRITE"}
        return FileAgent(matrix, queue, allowed_paths=allowed, prohibited_paths=prohibited or [])

    def test_delete_file_creates_proposal(self, tmp_path):
        target = tmp_path / "target.txt"
        target.write_text("bye")
        agent = self._make_agent(allowed={str(tmp_path): "READ_WRITE"})
        proposal = agent.delete_file(str(target), "cleanup")
        assert proposal.proposal_id == "del-001"

    def test_delete_file_not_found(self, tmp_path):
        agent = self._make_agent(allowed={str(tmp_path): "READ_WRITE"})
        with pytest.raises(FileNotFoundError):
            agent.delete_file(str(tmp_path / "missing.txt"), "x")

    def test_execute_approved_delete(self, tmp_path):
        target = tmp_path / "target.txt"
        target.write_text("bye")
        agent = self._make_agent(allowed={str(tmp_path): "READ_WRITE"})
        proposal = MagicMock()
        proposal.status = "approved"
        proposal.proposal_id = "del-001"
        proposal.tool_args = {"path": str(target)}
        agent.execute_approved_delete(proposal)
        assert not target.exists()

    def test_delete_read_only_scope_blocked(self, tmp_path):
        # Simulate the vault guard: source is READ-only
        read_only_dir = tmp_path / "vault"
        read_only_dir.mkdir()
        target = read_only_dir / "important.md"
        target.write_text("sacred")
        agent = self._make_agent(allowed={
            str(read_only_dir): "READ",
            str(tmp_path): "READ_WRITE",
        })
        with pytest.raises(PermissionError, match="PROHIBITED"):
            agent.delete_file(str(target), "bad")
