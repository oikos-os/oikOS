from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest


# ── Scope Validation ─────────────────────────────────────────────────


class TestFileAgentScope:
    def test_prohibited_path_blocked(self, tmp_path):
        from core.agency.file_agent import FileAgent
        agent = _make_agent(tmp_path)
        with pytest.raises(PermissionError, match="PROHIBITED"):
            agent.read_file("D:/Development/OIKOS_OMEGA/core/config.py")

    def test_prohibited_path_with_traversal_blocked(self, tmp_path):
        from core.agency.file_agent import FileAgent
        agent = _make_agent(tmp_path)
        with pytest.raises(PermissionError, match="PROHIBITED"):
            agent.read_file("D:/Development/OIKOS_OMEGA/../OIKOS_OMEGA/vault/secret.md")

    def test_prohibited_checked_before_allowed(self, tmp_path):
        from core.agency.file_agent import FileAgent
        agent = _make_agent(tmp_path)
        with pytest.raises(PermissionError, match="PROHIBITED"):
            agent.read_file("D:/Development/OIKOS_OMEGA/staging/test.txt")

    def test_allowed_read_path_succeeds(self, tmp_path):
        from core.agency.file_agent import FileAgent
        allowed_dir = tmp_path / "sigma_vault"
        allowed_dir.mkdir()
        test_file = allowed_dir / "test.md"
        test_file.write_text("vault content", encoding="utf-8")
        agent = _make_agent(tmp_path, allowed={str(allowed_dir): "READ"})
        result = agent.read_file(str(test_file))
        assert result == "vault content"

    def test_path_outside_all_scopes_blocked(self, tmp_path):
        from core.agency.file_agent import FileAgent
        agent = _make_agent(tmp_path)
        with pytest.raises(PermissionError, match="outside allowed scope"):
            agent.read_file("C:/Windows/System32/config.sys")

    def test_write_to_read_only_path_blocked(self, tmp_path):
        from core.agency.file_agent import FileAgent
        read_dir = tmp_path / "read_only"
        read_dir.mkdir()
        agent = _make_agent(tmp_path, allowed={str(read_dir): "READ"})
        with pytest.raises(PermissionError, match="read-only"):
            agent.write_file(str(read_dir / "test.txt"), "content", "test reason")

    def test_path_traversal_out_of_scope_blocked(self, tmp_path):
        from core.agency.file_agent import FileAgent
        allowed_dir = tmp_path / "staging"
        allowed_dir.mkdir()
        agent = _make_agent(tmp_path, allowed={str(allowed_dir): "READ_WRITE"})
        escape_path = str(allowed_dir / ".." / "secret.txt")
        with pytest.raises(PermissionError):
            agent.read_file(escape_path)


# ── Read Operations ──────────────────────────────────────────────────


class TestFileAgentRead:
    def test_read_file_returns_content(self, tmp_path):
        from core.agency.file_agent import FileAgent
        allowed = tmp_path / "data"
        allowed.mkdir()
        f = allowed / "hello.txt"
        f.write_text("hello world", encoding="utf-8")
        agent = _make_agent(tmp_path, allowed={str(allowed): "READ"})
        assert agent.read_file(str(f)) == "hello world"

    def test_read_nonexistent_file_raises(self, tmp_path):
        from core.agency.file_agent import FileAgent
        allowed = tmp_path / "data"
        allowed.mkdir()
        agent = _make_agent(tmp_path, allowed={str(allowed): "READ"})
        with pytest.raises(FileNotFoundError):
            agent.read_file(str(allowed / "missing.txt"))

    def test_read_logs_operation(self, tmp_path):
        from core.agency.file_agent import FileAgent
        allowed = tmp_path / "data"
        allowed.mkdir()
        f = allowed / "test.md"
        f.write_text("content", encoding="utf-8")
        log_path = tmp_path / "file_ops.jsonl"
        agent = _make_agent(tmp_path, allowed={str(allowed): "READ"}, log_path=log_path)
        agent.read_file(str(f))
        lines = log_path.read_text(encoding="utf-8").strip().split("\n")
        record = json.loads(lines[0])
        assert record["operation"] == "read"
        assert record["status"] == "success"

    def test_read_emits_event(self, tmp_path):
        from core.agency.file_agent import FileAgent
        allowed = tmp_path / "data"
        allowed.mkdir()
        f = allowed / "test.md"
        f.write_text("x", encoding="utf-8")
        agent = _make_agent(tmp_path, allowed={str(allowed): "READ"})
        with patch("core.agency.file_agent.emit_event") as mock:
            agent.read_file(str(f))
            mock.assert_called_once()
            assert mock.call_args[0][0] == "agency"
            assert mock.call_args[0][1] == "file_read"


# ── List Directory ───────────────────────────────────────────────────


class TestFileAgentListDir:
    def test_list_directory_returns_entries(self, tmp_path):
        from core.agency.file_agent import FileAgent
        allowed = tmp_path / "data"
        allowed.mkdir()
        (allowed / "a.txt").write_text("a", encoding="utf-8")
        (allowed / "b.md").write_text("b", encoding="utf-8")
        agent = _make_agent(tmp_path, allowed={str(allowed): "READ"})
        entries = agent.list_directory(str(allowed))
        assert sorted(entries) == ["a.txt", "b.md"]

    def test_list_directory_outside_scope_blocked(self, tmp_path):
        from core.agency.file_agent import FileAgent
        agent = _make_agent(tmp_path)
        with pytest.raises(PermissionError):
            agent.list_directory("C:/Windows")


# ── Write Operations ─────────────────────────────────────────────────


class TestFileAgentWrite:
    def test_write_returns_proposal(self, tmp_path):
        from core.agency.file_agent import FileAgent
        write_dir = tmp_path / "staging"
        write_dir.mkdir()
        agent = _make_agent(tmp_path, allowed={str(write_dir): "READ_WRITE"})
        proposal = agent.write_file(str(write_dir / "output.txt"), "content", "save results")
        assert proposal.status == "pending"
        assert proposal.action_type == "write_file"

    def test_write_logs_proposed(self, tmp_path):
        from core.agency.file_agent import FileAgent
        write_dir = tmp_path / "staging"
        write_dir.mkdir()
        log_path = tmp_path / "file_ops.jsonl"
        agent = _make_agent(tmp_path, allowed={str(write_dir): "READ_WRITE"}, log_path=log_path)
        agent.write_file(str(write_dir / "output.txt"), "content", "test")
        lines = log_path.read_text(encoding="utf-8").strip().split("\n")
        record = json.loads(lines[0])
        assert record["operation"] == "write"
        assert record["status"] == "proposed"

    def test_execute_approved_write_creates_file(self, tmp_path):
        from core.agency.file_agent import FileAgent
        write_dir = tmp_path / "staging"
        write_dir.mkdir()
        agent = _make_agent(tmp_path, allowed={str(write_dir): "READ_WRITE"})
        proposal = agent.write_file(str(write_dir / "output.txt"), "hello world", "test")
        agent._queue.approve(proposal.proposal_id)
        agent.execute_approved_write(proposal, "hello world")
        assert (write_dir / "output.txt").read_text(encoding="utf-8") == "hello world"

    def test_execute_unapproved_write_raises(self, tmp_path):
        from core.agency.file_agent import FileAgent
        write_dir = tmp_path / "staging"
        write_dir.mkdir()
        agent = _make_agent(tmp_path, allowed={str(write_dir): "READ_WRITE"})
        proposal = agent.write_file(str(write_dir / "out.txt"), "x", "test")
        with pytest.raises(ValueError, match="not approved"):
            agent.execute_approved_write(proposal, "x")

    def test_write_creates_parent_dirs(self, tmp_path):
        from core.agency.file_agent import FileAgent
        write_dir = tmp_path / "staging"
        write_dir.mkdir()
        agent = _make_agent(tmp_path, allowed={str(write_dir): "READ_WRITE"})
        deep_path = str(write_dir / "sub" / "dir" / "file.md")
        proposal = agent.write_file(deep_path, "deep", "test")
        agent._queue.approve(proposal.proposal_id)
        agent.execute_approved_write(proposal, "deep")
        assert Path(deep_path).read_text(encoding="utf-8") == "deep"

    def test_write_to_prohibited_blocked(self, tmp_path):
        from core.agency.file_agent import FileAgent
        agent = _make_agent(tmp_path)
        with pytest.raises(PermissionError, match="PROHIBITED"):
            agent.write_file("D:/Development/OIKOS_OMEGA/evil.py", "bad", "evil")


# ── Move Operations ──────────────────────────────────────────────────


class TestFileAgentMove:
    def test_move_returns_proposal(self, tmp_path):
        from core.agency.file_agent import FileAgent
        src_dir = tmp_path / "src"
        dst_dir = tmp_path / "dst"
        src_dir.mkdir()
        dst_dir.mkdir()
        (src_dir / "file.txt").write_text("content", encoding="utf-8")
        agent = _make_agent(tmp_path, allowed={
            str(src_dir): "READ_WRITE",
            str(dst_dir): "READ_WRITE",
        })
        proposal = agent.move_file(str(src_dir / "file.txt"), str(dst_dir / "file.txt"), "organize")
        assert proposal.status == "pending"
        assert proposal.action_type == "move_file"

    def test_execute_approved_move(self, tmp_path):
        from core.agency.file_agent import FileAgent
        src_dir = tmp_path / "src"
        dst_dir = tmp_path / "dst"
        src_dir.mkdir()
        dst_dir.mkdir()
        (src_dir / "file.txt").write_text("content", encoding="utf-8")
        agent = _make_agent(tmp_path, allowed={
            str(src_dir): "READ_WRITE",
            str(dst_dir): "READ_WRITE",
        })
        proposal = agent.move_file(str(src_dir / "file.txt"), str(dst_dir / "file.txt"), "test")
        agent._queue.approve(proposal.proposal_id)
        agent.execute_approved_move(proposal)
        assert not (src_dir / "file.txt").exists()
        assert (dst_dir / "file.txt").read_text(encoding="utf-8") == "content"

    def test_move_nonexistent_source_raises(self, tmp_path):
        from core.agency.file_agent import FileAgent
        src_dir = tmp_path / "src"
        dst_dir = tmp_path / "dst"
        src_dir.mkdir()
        dst_dir.mkdir()
        agent = _make_agent(tmp_path, allowed={
            str(src_dir): "READ_WRITE",
            str(dst_dir): "READ_WRITE",
        })
        with pytest.raises(FileNotFoundError):
            agent.move_file(str(src_dir / "nope.txt"), str(dst_dir / "nope.txt"), "test")

    def test_move_to_read_only_blocked(self, tmp_path):
        from core.agency.file_agent import FileAgent
        src_dir = tmp_path / "src"
        read_dir = tmp_path / "read"
        src_dir.mkdir()
        read_dir.mkdir()
        (src_dir / "file.txt").write_text("x", encoding="utf-8")
        agent = _make_agent(tmp_path, allowed={
            str(src_dir): "READ_WRITE",
            str(read_dir): "READ",
        })
        with pytest.raises(PermissionError, match="read-only"):
            agent.move_file(str(src_dir / "file.txt"), str(read_dir / "file.txt"), "test")

    def test_move_from_read_only_blocked(self, tmp_path):
        from core.agency.file_agent import FileAgent
        read_dir = tmp_path / "readonly"
        dst_dir = tmp_path / "dst"
        read_dir.mkdir()
        dst_dir.mkdir()
        (read_dir / "file.txt").write_text("x", encoding="utf-8")
        agent = _make_agent(tmp_path, allowed={
            str(read_dir): "READ",
            str(dst_dir): "READ_WRITE",
        })
        with pytest.raises(PermissionError, match="read-only"):
            agent.move_file(str(read_dir / "file.txt"), str(dst_dir / "file.txt"), "test")

    def test_rename_within_directory(self, tmp_path):
        from core.agency.file_agent import FileAgent
        d = tmp_path / "data"
        d.mkdir()
        (d / "old.txt").write_text("content", encoding="utf-8")
        agent = _make_agent(tmp_path, allowed={str(d): "READ_WRITE"})
        proposal = agent.move_file(str(d / "old.txt"), str(d / "new.txt"), "rename")
        agent._queue.approve(proposal.proposal_id)
        agent.execute_approved_move(proposal)
        assert not (d / "old.txt").exists()
        assert (d / "new.txt").read_text(encoding="utf-8") == "content"


# ── Search Operations ────────────────────────────────────────────────


class TestFileAgentSearch:
    def test_search_files_returns_matches(self, tmp_path):
        from core.agency.file_agent import FileAgent
        d = tmp_path / "data"
        d.mkdir()
        (d / "report.md").write_text("r", encoding="utf-8")
        (d / "notes.md").write_text("n", encoding="utf-8")
        (d / "code.py").write_text("c", encoding="utf-8")
        agent = _make_agent(tmp_path, allowed={str(d): "READ"})
        matches = agent.search_files(str(d), "*.md")
        assert len(matches) == 2
        assert all(m.endswith(".md") for m in matches)

    def test_search_files_no_matches(self, tmp_path):
        from core.agency.file_agent import FileAgent
        d = tmp_path / "data"
        d.mkdir()
        agent = _make_agent(tmp_path, allowed={str(d): "READ"})
        assert agent.search_files(str(d), "*.xyz") == []

    def test_search_files_traversal_pattern_blocked(self, tmp_path):
        from core.agency.file_agent import FileAgent
        d = tmp_path / "data"
        d.mkdir()
        agent = _make_agent(tmp_path, allowed={str(d): "READ"})
        with pytest.raises(ValueError, match="Path traversal"):
            agent.search_files(str(d), "../../**/*")

    def test_search_files_outside_scope_blocked(self, tmp_path):
        from core.agency.file_agent import FileAgent
        agent = _make_agent(tmp_path)
        with pytest.raises(PermissionError):
            agent.search_files("C:/Windows", "*.dll")

    def test_search_files_logs_operation(self, tmp_path):
        from core.agency.file_agent import FileAgent
        d = tmp_path / "data"
        d.mkdir()
        log_path = tmp_path / "file_ops.jsonl"
        agent = _make_agent(tmp_path, allowed={str(d): "READ"}, log_path=log_path)
        agent.search_files(str(d), "*.md")
        lines = log_path.read_text(encoding="utf-8").strip().split("\n")
        record = json.loads(lines[0])
        assert record["operation"] == "search"

    def test_search_vault_delegates_to_hybrid_search(self, tmp_path):
        from core.agency.file_agent import FileAgent
        agent = _make_agent(tmp_path)
        mock_result = MagicMock()
        mock_result.source_path = "vault/knowledge/test.md"
        mock_result.header_path = "Test"
        mock_result.content = "test content"
        mock_result.tier.value = "semantic"
        mock_result.final_score = 0.85
        with patch("core.memory.search.hybrid_search", return_value=[mock_result]) as mock_search:
            results = agent.search_vault("test query")
            mock_search.assert_called_once_with("test query", limit=10)
            assert len(results) == 1
            assert results[0]["source_path"] == "vault/knowledge/test.md"
            assert results[0]["score"] == 0.85


# ── Integration: Full Pipeline ───────────────────────────────────────


class TestFileAgentIntegration:
    def test_full_write_pipeline(self, tmp_path):
        """Classify -> propose -> approve -> execute -> verify."""
        from core.agency.file_agent import FileAgent
        write_dir = tmp_path / "staging"
        write_dir.mkdir()
        agent = _make_agent(tmp_path, allowed={str(write_dir): "READ_WRITE"})

        # 1. Write proposes (async, per SYNTH ruling)
        proposal = agent.write_file(str(write_dir / "result.md"), "# Research\nFindings here.", "save research")
        assert proposal.status == "pending"

        # 2. Architect approves
        agent._queue.approve(proposal.proposal_id)

        # 3. Execute the approved write
        agent.execute_approved_write(proposal, "# Research\nFindings here.")
        assert (write_dir / "result.md").read_text(encoding="utf-8") == "# Research\nFindings here."

    def test_full_move_pipeline(self, tmp_path):
        """Move: propose -> approve -> execute."""
        from core.agency.file_agent import FileAgent
        src = tmp_path / "inbox"
        dst = tmp_path / "processed"
        src.mkdir()
        dst.mkdir()
        (src / "item.md").write_text("data", encoding="utf-8")
        agent = _make_agent(tmp_path, allowed={
            str(src): "READ_WRITE",
            str(dst): "READ_WRITE",
        })
        proposal = agent.move_file(str(src / "item.md"), str(dst / "item.md"), "archive")
        agent._queue.approve(proposal.proposal_id)
        agent.execute_approved_move(proposal)
        assert (dst / "item.md").exists()
        assert not (src / "item.md").exists()

    def test_read_then_write_pipeline(self, tmp_path):
        """Read source -> process -> write result."""
        from core.agency.file_agent import FileAgent
        read_dir = tmp_path / "vault"
        write_dir = tmp_path / "staging"
        read_dir.mkdir()
        write_dir.mkdir()
        (read_dir / "source.md").write_text("Original content", encoding="utf-8")
        agent = _make_agent(tmp_path, allowed={
            str(read_dir): "READ",
            str(write_dir): "READ_WRITE",
        })
        content = agent.read_file(str(read_dir / "source.md"))
        processed = f"# Summary\n{content}"
        proposal = agent.write_file(str(write_dir / "summary.md"), processed, "summarize source")
        agent._queue.approve(proposal.proposal_id)
        agent.execute_approved_write(proposal, processed)
        assert (write_dir / "summary.md").read_text(encoding="utf-8") == "# Summary\nOriginal content"

    def test_oikos_omega_sacred_boundary(self, tmp_path):
        """No operation can touch OIKOS_OMEGA — hardcoded doctrine."""
        from core.agency.file_agent import FileAgent
        agent = _make_agent(tmp_path)
        with pytest.raises(PermissionError, match="PROHIBITED"):
            agent.read_file("D:/Development/OIKOS_OMEGA/core/interface/config.py")
        with pytest.raises(PermissionError, match="PROHIBITED"):
            agent.write_file("D:/Development/OIKOS_OMEGA/evil.py", "x", "evil")
        with pytest.raises(PermissionError, match="PROHIBITED"):
            agent.list_directory("D:/Development/OIKOS_OMEGA/core/")

    def test_audit_trail_complete(self, tmp_path):
        """All operations produce JSONL audit entries."""
        from core.agency.file_agent import FileAgent
        d = tmp_path / "data"
        d.mkdir()
        (d / "test.md").write_text("content", encoding="utf-8")
        log_path = tmp_path / "file_ops.jsonl"
        agent = _make_agent(tmp_path, allowed={str(d): "READ_WRITE"}, log_path=log_path)
        agent.read_file(str(d / "test.md"))
        agent.list_directory(str(d))
        agent.search_files(str(d), "*.md")
        agent.write_file(str(d / "new.md"), "x", "test")
        lines = log_path.read_text(encoding="utf-8").strip().split("\n")
        ops = [json.loads(l)["operation"] for l in lines]
        assert ops == ["read", "list", "search", "write"]


# ── Helper ───────────────────────────────────────────────────────────


def _make_agent(tmp_path, allowed=None, prohibited=None, log_path=None):
    from core.agency.file_agent import FileAgent
    from core.agency.autonomy import AutonomyMatrix
    from core.agency.approval import ApprovalQueue
    import json as _json

    matrix_config = {
        "version": "1.0",
        "actions": {
            "read_file": {"category": "SAFE"},
            "write_file": {"category": "ASK_FIRST"},
            "move_file": {"category": "ASK_FIRST"},
            "list_directory": {"category": "SAFE"},
            "search_files": {"category": "SAFE"},
            "delete_vault": {"category": "PROHIBITED"},
        },
    }
    matrix_file = tmp_path / "matrix.json"
    matrix_file.write_text(_json.dumps(matrix_config), encoding="utf-8")
    matrix = AutonomyMatrix(matrix_file)
    queue = ApprovalQueue(tmp_path / "proposals.jsonl")

    return FileAgent(
        matrix=matrix,
        queue=queue,
        allowed_paths=allowed or {},
        prohibited_paths=prohibited or ["D:/Development/OIKOS_OMEGA"],
        log_path=log_path or tmp_path / "file_ops.jsonl",
    )
