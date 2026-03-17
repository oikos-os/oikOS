"""Tests for Phase 7e Module 1 — Core Tools registration and direct calls."""

import pytest
from unittest.mock import MagicMock, patch

from core.framework.decorator import clear_registry, get_registered_tools


class TestToolRegistration:
    """Tests that importing core.framework.tools registers all expected tools."""

    def test_all_tools_register(self):
        clear_registry()
        import importlib
        import core.framework.tools.vault_tools as vt
        import core.framework.tools.system_tools as st
        import core.framework.tools.inference_tools as it
        import core.framework.tools.fs_tools as ft
        for m in [vt, st, it, ft]:
            importlib.reload(m)

        tools = get_registered_tools()
        expected = [
            "oikos_vault_search", "oikos_vault_compile", "oikos_vault_index",
            "oikos_system_status", "oikos_state_get", "oikos_state_transition",
            "oikos_gauntlet_run", "oikos_session_start", "oikos_session_close",
            "oikos_ollama_generate", "oikos_provider_query",
            "oikos_fs_read", "oikos_fs_list", "oikos_fs_search",
            "oikos_fs_write", "oikos_fs_edit",
        ]
        for name in expected:
            assert name in tools, f"Missing tool: {name}"
        assert len(tools) >= 16

    def test_vault_tools_are_never_leave(self):
        from core.interface.models import DataTier
        import core.framework.tools.vault_tools  # noqa: F401
        tools = get_registered_tools()
        for name in ["oikos_vault_search", "oikos_vault_compile", "oikos_vault_index"]:
            assert name in tools, f"Missing: {name}"
            _, meta = tools[name]
            assert meta.privacy == DataTier.NEVER_LEAVE, f"{name} should be NEVER_LEAVE"

    def test_write_tools_are_ask_first(self):
        from core.interface.models import ActionClass
        import core.framework.tools.fs_tools  # noqa: F401
        import core.framework.tools.system_tools  # noqa: F401
        tools = get_registered_tools()
        for name in ["oikos_fs_write", "oikos_fs_edit", "oikos_state_transition"]:
            assert name in tools, f"Missing: {name}"
            _, meta = tools[name]
            assert meta.autonomy == ActionClass.ASK_FIRST, f"{name} should be ASK_FIRST"


class TestVaultToolsDirect:
    def test_vault_search_callable(self):
        from core.framework.tools.vault_tools import vault_search
        assert callable(vault_search)

    def test_vault_compile_callable(self):
        from core.framework.tools.vault_tools import vault_compile
        assert callable(vault_compile)


class TestSystemToolsDirect:
    def test_state_get(self):
        from core.framework.tools.system_tools import state_get
        from core.autonomic.fsm import SystemState
        with patch("core.autonomic.fsm.get_current_state", return_value=SystemState.IDLE), \
             patch("core.autonomic.fsm.get_last_transition_time", return_value="2026-03-15T12:00:00"):
            result = state_get()
        assert result["state"] == "idle"

    def test_session_start(self):
        from core.framework.tools.system_tools import session_start
        mock_session = {"session_id": "test-123", "created": "2026-03-15"}
        with patch("core.memory.session.get_or_create_session", return_value=mock_session):
            result = session_start()
        assert result["session_id"] == "test-123"


class TestInferenceToolsDirect:
    def test_ollama_generate(self):
        from core.framework.tools.inference_tools import ollama_generate
        mock_result = {"response": "Hello!", "model": "qwen2.5:14b", "eval_count": 10}
        with patch("core.cognition.inference.generate_local", return_value=mock_result):
            result = ollama_generate("Say hello")
        assert result["response"] == "Hello!"

    def test_provider_query(self):
        from core.framework.tools.inference_tools import provider_query
        mock_resp = MagicMock()
        mock_resp.text = "Answer"
        mock_resp.model_used = "qwen2.5:14b"
        mock_resp.route = "LOCAL"
        mock_resp.confidence = 0.85
        mock_resp.pii_scrubbed = False
        with patch("core.cognition.handler.execute_query", return_value=mock_resp):
            result = provider_query("What is oikOS?")
        assert result["text"] == "Answer"


class TestFsToolsDirect:
    def test_fs_read(self):
        from core.framework.tools.fs_tools import fs_read
        mock_agent = MagicMock()
        mock_agent.read_file.return_value = "file content"
        with patch("core.framework.tools.fs_tools._file_agent", mock_agent):
            result = fs_read("/some/path.txt")
        assert result["content"] == "file content"
        assert result["length"] == 12

    def test_fs_list(self):
        from core.framework.tools.fs_tools import fs_list
        mock_agent = MagicMock()
        mock_agent.list_directory.return_value = ["a.txt", "b.txt"]
        with patch("core.framework.tools.fs_tools._file_agent", mock_agent):
            result = fs_list("/some/dir")
        assert result["count"] == 2

    def test_fs_write_creates_proposal(self):
        from core.framework.tools.fs_tools import fs_write
        mock_agent = MagicMock()
        mock_proposal = MagicMock()
        mock_proposal.proposal_id = "prop-456"
        mock_agent.write_file.return_value = mock_proposal
        with patch("core.framework.tools.fs_tools._file_agent", mock_agent):
            result = fs_write("/some/file.txt", "new content", "test write")
        assert result["status"] == "proposal_created"
        assert result["proposal_id"] == "prop-456"

    def test_fs_edit_not_found(self):
        from core.framework.tools.fs_tools import fs_edit
        mock_agent = MagicMock()
        mock_agent.read_file.return_value = "original content"
        with patch("core.framework.tools.fs_tools._file_agent", mock_agent):
            result = fs_edit("/file.txt", "nonexistent", "replacement")
        assert result["status"] == "error"

    def test_fs_edit_creates_proposal(self):
        from core.framework.tools.fs_tools import fs_edit
        mock_agent = MagicMock()
        mock_agent.read_file.return_value = "hello world"
        mock_proposal = MagicMock()
        mock_proposal.proposal_id = "prop-789"
        mock_agent.write_file.return_value = mock_proposal
        with patch("core.framework.tools.fs_tools._file_agent", mock_agent):
            result = fs_edit("/file.txt", "hello", "goodbye", "test edit")
        assert result["status"] == "proposal_created"
        written_content = mock_agent.write_file.call_args[0][1]
        assert written_content == "goodbye world"
