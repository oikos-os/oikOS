# File Management Agent Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Give KAIROS scoped file management capabilities — read, write, move, search — with hardcoded safety boundaries and autonomy matrix enforcement.

**Architecture:** FileAgent class with scope validation (PROHIBITED hardcoded, allowed paths in config), async write proposals via ApprovalQueue, vault search delegation to existing hybrid_search, JSONL audit logging. Zero LLM calls.

**Tech Stack:** Python 3.12+, pathlib, pytest

**SYNTH Rulings Applied:**
- Async writes — return ActionProposal immediately, no blocking
- Separate ScopeValidator in FileAgent (Option B) — Module 2 untouched
- Allowed paths in config.py, PROHIBITED paths hardcoded (doctrine, not configuration)
- Write-only staging — no PromotionProposal, Architect ingests later
- Explicit directory for search_files() — no cross-directory
- Both moves and renames supported via same move_file()
- PROHIBITED check FIRST, before any scope rule
- Budget enforcement: 2K input ceiling before reading large files

**Branch:** `feature/phase-7d-the-hands` (continue from Module 2 commits)

---

## Task 1: Config Constants for File Agent Scope

**Files:**
- Modify: `core/interface/config.py:229` (add after APPROVAL_PROPOSALS_LOG)

**Step 1: Add config constants**

After `APPROVAL_PROPOSALS_LOG = AGENCY_LOG_DIR / "proposals.jsonl"` (line 229), add:

```python
# ── File Management Agent (Phase 7d Module 3) ───────────────────────
FILE_OPS_LOG = AGENCY_LOG_DIR / "file_ops.jsonl"
FILE_AGENT_ALLOWED_PATHS: dict[str, str] = {
    "D:/SIGMA/Vault/SIGMA_VAULT": "READ",
    "D:/COMMAND/staging": "READ_WRITE",
    "D:/COMMAND/messages": "READ_WRITE",
}
```

**Step 2: Update autonomy_matrix.json**

Add `move_file` and `list_directory` action types:

```json
"move_file": {"category": "ASK_FIRST"},
"list_directory": {"category": "SAFE"}
```

**Step 3: Commit**

```bash
git add core/interface/config.py autonomy_matrix.json
git commit -m "feat(agency): add File Agent config constants and action types (Phase 7d Module 3)"
```

---

## Task 2: FileAgent Core — Scope Validation + Read

**Files:**
- Create: `core/agency/file_agent.py`
- Create: `tests/test_file_agent.py`

**Step 1: Write the failing tests**

Create `tests/test_file_agent.py`:

```python
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest


# ── Scope Validation ─────────────────────────────────────────────────


class TestFileAgentScope:
    def test_prohibited_path_blocked(self, tmp_path):
        """OIKOS_OMEGA is sacred — always blocked."""
        from core.agency.file_agent import FileAgent
        agent = _make_agent(tmp_path)
        with pytest.raises(PermissionError, match="PROHIBITED"):
            agent.read_file("D:/Development/OIKOS_OMEGA/core/config.py")

    def test_prohibited_path_with_traversal_blocked(self, tmp_path):
        """Path traversal into OIKOS_OMEGA is blocked."""
        from core.agency.file_agent import FileAgent
        agent = _make_agent(tmp_path)
        with pytest.raises(PermissionError, match="PROHIBITED"):
            agent.read_file("D:/Development/OIKOS_OMEGA/../OIKOS_OMEGA/vault/secret.md")

    def test_prohibited_checked_before_allowed(self, tmp_path):
        """Even if a subpath looks allowed, PROHIBITED wins."""
        from core.agency.file_agent import FileAgent
        agent = _make_agent(tmp_path)
        with pytest.raises(PermissionError, match="PROHIBITED"):
            agent.read_file("D:/Development/OIKOS_OMEGA/staging/test.txt")

    def test_allowed_read_path_succeeds(self, tmp_path):
        """Read from allowed READ directory succeeds."""
        from core.agency.file_agent import FileAgent
        allowed_dir = tmp_path / "sigma_vault"
        allowed_dir.mkdir()
        test_file = allowed_dir / "test.md"
        test_file.write_text("vault content", encoding="utf-8")
        agent = _make_agent(tmp_path, allowed={str(allowed_dir): "READ"})
        result = agent.read_file(str(test_file))
        assert result == "vault content"

    def test_path_outside_all_scopes_blocked(self, tmp_path):
        """Path not in any allowed or prohibited list is blocked."""
        from core.agency.file_agent import FileAgent
        agent = _make_agent(tmp_path)
        with pytest.raises(PermissionError, match="outside allowed scope"):
            agent.read_file("C:/Windows/System32/config.sys")

    def test_write_to_read_only_path_blocked(self, tmp_path):
        """Write to READ-only directory is blocked."""
        from core.agency.file_agent import FileAgent
        read_dir = tmp_path / "read_only"
        read_dir.mkdir()
        agent = _make_agent(tmp_path, allowed={str(read_dir): "READ"})
        with pytest.raises(PermissionError, match="read-only"):
            agent.write_file(str(read_dir / "test.txt"), "content", "test reason")

    def test_path_traversal_out_of_scope_blocked(self, tmp_path):
        """Traversal escaping allowed directory is blocked."""
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
```

**Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_file_agent.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.agency.file_agent'`

**Step 3: Write implementation**

Create `core/agency/file_agent.py`:

```python
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from core.autonomic.events import emit_event
from core.interface.models import ActionClass, ActionProposal

log = logging.getLogger(__name__)

# Sacred boundary — hardcoded, not configurable (SYNTH ruling)
_PROHIBITED_PATHS_DEFAULT: list[str] = [
    "D:/Development/OIKOS_OMEGA",
]


class FileAgent:
    def __init__(
        self,
        matrix,
        queue,
        allowed_paths: dict[str, str] | None = None,
        prohibited_paths: list[str] | None = None,
        log_path: Path | None = None,
    ):
        from core.interface.config import FILE_AGENT_ALLOWED_PATHS, FILE_OPS_LOG

        self._matrix = matrix
        self._queue = queue
        self._allowed = allowed_paths if allowed_paths is not None else dict(FILE_AGENT_ALLOWED_PATHS)
        self._prohibited = prohibited_paths if prohibited_paths is not None else list(_PROHIBITED_PATHS_DEFAULT)
        self._log_path = log_path or FILE_OPS_LOG

    # ── Scope Validation ─────────────────────────────────────────────

    def _resolve_path(self, path: str) -> Path:
        return Path(path).resolve()

    def _check_prohibited(self, resolved: Path) -> None:
        for p in self._prohibited:
            try:
                if resolved.is_relative_to(Path(p).resolve()):
                    raise PermissionError(f"PROHIBITED: {resolved}")
            except (ValueError, OSError):
                continue

    def _find_allowed_scope(self, resolved: Path) -> str | None:
        for allowed_path, permission in self._allowed.items():
            try:
                if resolved.is_relative_to(Path(allowed_path).resolve()):
                    return permission
            except (ValueError, OSError):
                continue
        return None

    def _validate_read(self, path: str) -> Path:
        resolved = self._resolve_path(path)
        self._check_prohibited(resolved)
        permission = self._find_allowed_scope(resolved)
        if permission is None:
            raise PermissionError(f"Path outside allowed scope: {resolved}")
        return resolved

    def _validate_write(self, path: str) -> Path:
        resolved = self._resolve_path(path)
        self._check_prohibited(resolved)
        permission = self._find_allowed_scope(resolved)
        if permission is None:
            raise PermissionError(f"Path outside allowed scope: {resolved}")
        if permission == "READ":
            raise PermissionError(f"Path is read-only: {resolved}")
        return resolved

    # ── Logging ──────────────────────────────────────────────────────

    def _log_op(self, operation: str, path: str, status: str, **extra) -> None:
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "operation": operation,
            "path": path,
            "status": status,
            **extra,
        }
        try:
            self._log_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record) + "\n")
        except OSError:
            log.warning("File ops log write failed")

    # ── Operations ───────────────────────────────────────────────────

    def read_file(self, path: str) -> str:
        resolved = self._validate_read(path)
        if not resolved.exists():
            raise FileNotFoundError(f"File not found: {resolved}")
        content = resolved.read_text(encoding="utf-8")
        self._log_op("read", str(resolved), "success")
        emit_event("agency", "file_read", {"path": str(resolved)})
        return content

    def list_directory(self, path: str) -> list[str]:
        resolved = self._validate_read(path)
        if not resolved.is_dir():
            raise NotADirectoryError(f"Not a directory: {resolved}")
        entries = sorted(p.name for p in resolved.iterdir())
        self._log_op("list", str(resolved), "success")
        return entries

    def write_file(self, path: str, content: str, reason: str) -> ActionProposal:
        resolved = self._validate_write(path)
        classification = self._matrix.classify("write_file")
        if classification == ActionClass.PROHIBITED:
            self._log_op("write", str(resolved), "blocked", reason="PROHIBITED")
            emit_event("agency", "file_blocked", {"path": str(resolved), "action": "write"})
            raise PermissionError(f"PROHIBITED: write to {resolved}")
        proposal = self._queue.propose(
            action_type="write_file",
            tool_name="file_write",
            tool_args={"path": str(resolved), "content_length": len(content)},
            reason=reason,
            estimated_tokens=int(len(content.split()) * 1.3),
        )
        # Store content for later execution
        proposal._pending_content = content
        self._log_op("write", str(resolved), "proposed", proposal_id=proposal.proposal_id)
        emit_event("agency", "proposal_created", {
            "proposal_id": proposal.proposal_id,
            "action": "write_file",
            "path": str(resolved),
        })
        return proposal

    def execute_approved_write(self, proposal: ActionProposal, content: str) -> None:
        if proposal.status != "approved":
            raise ValueError(f"Proposal {proposal.proposal_id!r} not approved (status: {proposal.status!r})")
        path = Path(proposal.tool_args["path"])
        self._check_prohibited(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        self._log_op("write", str(path), "executed", proposal_id=proposal.proposal_id)
        emit_event("agency", "file_write", {"path": str(path), "proposal_id": proposal.proposal_id})

    def move_file(self, src: str, dst: str, reason: str) -> ActionProposal:
        src_resolved = self._validate_read(src)
        dst_resolved = self._validate_write(dst)
        if not src_resolved.exists():
            raise FileNotFoundError(f"Source not found: {src_resolved}")
        proposal = self._queue.propose(
            action_type="move_file",
            tool_name="file_move",
            tool_args={"src": str(src_resolved), "dst": str(dst_resolved)},
            reason=reason,
            estimated_tokens=0,
        )
        self._log_op("move", str(src_resolved), "proposed",
                      dst=str(dst_resolved), proposal_id=proposal.proposal_id)
        return proposal

    def execute_approved_move(self, proposal: ActionProposal) -> None:
        if proposal.status != "approved":
            raise ValueError(f"Proposal {proposal.proposal_id!r} not approved")
        src = Path(proposal.tool_args["src"])
        dst = Path(proposal.tool_args["dst"])
        self._check_prohibited(dst)
        dst.parent.mkdir(parents=True, exist_ok=True)
        src.rename(dst)
        self._log_op("move", str(src), "executed",
                      dst=str(dst), proposal_id=proposal.proposal_id)
        emit_event("agency", "file_move", {"src": str(src), "dst": str(dst)})

    def search_files(self, directory: str, pattern: str) -> list[str]:
        resolved = self._validate_read(directory)
        if not resolved.is_dir():
            raise NotADirectoryError(f"Not a directory: {resolved}")
        matches = sorted(str(p) for p in resolved.glob(pattern))
        self._log_op("search", str(resolved), "success", pattern=pattern, matches=len(matches))
        return matches

    def search_vault(self, query: str, limit: int = 10) -> list[dict]:
        from core.memory.search import hybrid_search
        results = hybrid_search(query, limit=limit)
        self._log_op("vault_search", "vault", "success", query=query, results=len(results))
        return [
            {
                "source_path": r.source_path,
                "header_path": r.header_path,
                "content": r.content,
                "tier": r.tier.value,
                "score": r.final_score,
            }
            for r in results
        ]
```

**Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_file_agent.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add core/agency/file_agent.py tests/test_file_agent.py
git commit -m "feat(agency): add FileAgent with scope validation, read, list operations (Phase 7d Module 3)"
```

---

## Task 3: FileAgent — Write, Move, Search Operations + Tests

**Files:**
- Modify: `tests/test_file_agent.py` (add write, move, search test classes)

**Step 1: Append tests to `tests/test_file_agent.py`**

Add before the `_make_agent` helper (or after the existing test classes):

```python
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

    def test_rename_within_directory(self, tmp_path):
        """Rename = move within same directory."""
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
        with patch("core.agency.file_agent.hybrid_search", return_value=[mock_result]) as mock_search:
            results = agent.search_vault("test query")
            mock_search.assert_called_once_with("test query", limit=10)
            assert len(results) == 1
            assert results[0]["source_path"] == "vault/knowledge/test.md"
            assert results[0]["score"] == 0.85
```

**Step 2: Run tests to verify they pass**

Run: `python -m pytest tests/test_file_agent.py -v`
Expected: All PASS

**Step 3: Commit**

```bash
git add tests/test_file_agent.py
git commit -m "test(agency): add write, move, search tests for FileAgent (Phase 7d Module 3)"
```

---

## Task 4: Tool Registry Extension + Integration Tests

**Files:**
- Modify: `tests/test_file_agent.py` (add integration tests)

**Step 1: Append integration tests**

Add to `tests/test_file_agent.py`:

```python
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
```

**Step 2: Run all tests**

Run: `python -m pytest tests/test_file_agent.py -v`
Expected: All PASS

Run: `python -m pytest tests/ -x -q`
Expected: All pass, no regressions

**Step 3: Commit**

```bash
git add tests/test_file_agent.py
git commit -m "test(agency): add integration tests for FileAgent pipeline (Phase 7d Module 3)"
```

---

## Summary

| Task | Component | New Files | Modified Files | Est. Tests |
|------|-----------|-----------|----------------|------------|
| 1 | Config + JSON | — | `config.py`, `autonomy_matrix.json` | 0 |
| 2 | FileAgent core (scope + read + list) | `file_agent.py`, `test_file_agent.py` | — | 14 |
| 3 | Write, move, search tests | — | `test_file_agent.py` | 17 |
| 4 | Integration tests | — | `test_file_agent.py` | 5 |
| **Total** | | **2 new files** | **2 modified files** | **~36** |

**Commits:** 4 (one per task)
**LLM calls:** 0 (pure file operations, per SYNTH ruling)
**New dependencies:** 0 (via negativa)
