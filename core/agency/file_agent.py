from __future__ import annotations

import json
import logging
import shutil
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
                prohibited_resolved = Path(p).resolve()
            except (ValueError, OSError):
                continue
            if resolved.is_relative_to(prohibited_resolved):
                raise PermissionError(f"PROHIBITED: {resolved}")

    def _find_allowed_scope(self, resolved: Path) -> str | None:
        best_match: str | None = None
        best_depth = -1
        for allowed_path, permission in self._allowed.items():
            try:
                allowed_resolved = Path(allowed_path).resolve()
            except (ValueError, OSError):
                continue
            if resolved.is_relative_to(allowed_resolved):
                depth = len(allowed_resolved.parts)
                if depth > best_depth:
                    best_depth = depth
                    best_match = permission
        return best_match

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
        path = self._validate_write(proposal.tool_args["path"])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        self._log_op("write", str(path), "executed", proposal_id=proposal.proposal_id)
        emit_event("agency", "file_write", {"path": str(path), "proposal_id": proposal.proposal_id})

    def move_file(self, src: str, dst: str, reason: str) -> ActionProposal:
        src_resolved = self._validate_write(src)
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
        src = self._validate_write(proposal.tool_args["src"])
        dst = self._validate_write(proposal.tool_args["dst"])
        dst.parent.mkdir(parents=True, exist_ok=True)
        src.rename(dst)
        self._log_op("move", str(src), "executed",
                      dst=str(dst), proposal_id=proposal.proposal_id)
        emit_event("agency", "file_move", {"src": str(src), "dst": str(dst)})

    def copy_file(self, src: str, dst: str, reason: str) -> ActionProposal:
        src_resolved = self._validate_read(src)
        dst_resolved = self._validate_write(dst)
        if not src_resolved.exists():
            raise FileNotFoundError(f"Source not found: {src_resolved}")
        proposal = self._queue.propose(
            action_type="copy_file",
            tool_name="file_copy",
            tool_args={"src": str(src_resolved), "dst": str(dst_resolved)},
            reason=reason,
            estimated_tokens=0,
        )
        self._log_op("copy", str(src_resolved), "proposed",
                      dst=str(dst_resolved), proposal_id=proposal.proposal_id)
        return proposal

    def execute_approved_copy(self, proposal: ActionProposal) -> None:
        if proposal.status != "approved":
            raise ValueError(f"Proposal {proposal.proposal_id!r} not approved")
        src = self._validate_read(proposal.tool_args["src"])
        dst = self._validate_write(proposal.tool_args["dst"])
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        self._log_op("copy", str(src), "executed",
                      dst=str(dst), proposal_id=proposal.proposal_id)
        emit_event("agency", "file_copy", {"src": str(src), "dst": str(dst)})

    def delete_file(self, path: str, reason: str) -> ActionProposal:
        resolved = self._resolve_path(path)
        self._check_prohibited(resolved)
        permission = self._find_allowed_scope(resolved)
        if permission is None:
            raise PermissionError(f"Path outside allowed scope: {resolved}")
        if permission == "READ":
            raise PermissionError(f"PROHIBITED: delete from read-only scope: {resolved}")
        resolved = self._validate_write(path)
        if not resolved.exists():
            raise FileNotFoundError(f"File not found: {resolved}")
        proposal = self._queue.propose(
            action_type="delete_file",
            tool_name="file_delete",
            tool_args={"path": str(resolved)},
            reason=reason,
            estimated_tokens=0,
        )
        self._log_op("delete", str(resolved), "proposed", proposal_id=proposal.proposal_id)
        return proposal

    def execute_approved_delete(self, proposal: ActionProposal) -> None:
        if proposal.status != "approved":
            raise ValueError(f"Proposal {proposal.proposal_id!r} not approved")
        path = self._validate_write(proposal.tool_args["path"])
        path.unlink()
        self._log_op("delete", str(path), "executed", proposal_id=proposal.proposal_id)
        emit_event("agency", "file_delete", {"path": str(path)})

    def search_files(self, directory: str, pattern: str) -> list[str]:
        if any(part == ".." for part in Path(pattern).parts):
            raise ValueError(f"Path traversal in glob pattern: {pattern!r}")
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
