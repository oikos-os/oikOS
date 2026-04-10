from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.interface.models import ActionClass


# ── AutonomyMatrix: classification ───────────────────────────────────


class TestAutonomyMatrixClassification:
    def test_safe_action_classified(self, tmp_path):
        from core.agency.autonomy import AutonomyMatrix
        matrix = _make_matrix(tmp_path, {"read_file": {"category": "SAFE"}})
        assert matrix.classify("read_file") == ActionClass.SAFE

    def test_ask_first_action_classified(self, tmp_path):
        from core.agency.autonomy import AutonomyMatrix
        matrix = _make_matrix(tmp_path, {"write_file": {"category": "ASK_FIRST"}})
        assert matrix.classify("write_file") == ActionClass.ASK_FIRST

    def test_prohibited_action_classified(self, tmp_path):
        from core.agency.autonomy import AutonomyMatrix
        matrix = _make_matrix(tmp_path, {"delete_vault": {"category": "PROHIBITED"}})
        assert matrix.classify("delete_vault") == ActionClass.PROHIBITED

    def test_unknown_action_defaults_to_prohibited(self, tmp_path):
        from core.agency.autonomy import AutonomyMatrix
        matrix = _make_matrix(tmp_path, {"read_file": {"category": "SAFE"}})
        assert matrix.classify("unknown_action") == ActionClass.PROHIBITED

    def test_all_safe_actions_from_default_config(self, tmp_path):
        from core.agency.autonomy import AutonomyMatrix
        matrix = _make_matrix(tmp_path, {
            "read_file": {"category": "SAFE"},
            "search_files": {"category": "SAFE"},
            "check_status": {"category": "SAFE"},
            "read_web": {"category": "SAFE"},
            "vault_search": {"category": "SAFE"},
        })
        for action in ["read_file", "search_files", "check_status", "read_web", "vault_search"]:
            assert matrix.classify(action) == ActionClass.SAFE

    def test_all_prohibited_actions_from_default_config(self, tmp_path):
        from core.agency.autonomy import AutonomyMatrix
        matrix = _make_matrix(tmp_path, {
            "delete_vault": {"category": "PROHIBITED"},
            "modify_identity": {"category": "PROHIBITED"},
            "modify_source": {"category": "PROHIBITED"},
            "financial_transaction": {"category": "PROHIBITED"},
            "external_api_destructive": {"category": "PROHIBITED"},
        })
        for action in ["delete_vault", "modify_identity", "modify_source",
                        "financial_transaction", "external_api_destructive"]:
            assert matrix.classify(action) == ActionClass.PROHIBITED

    def test_scope_field_present_but_ignored(self, tmp_path):
        """Module 2 reads category only. Scope is for Module 3."""
        from core.agency.autonomy import AutonomyMatrix
        matrix = _make_matrix(tmp_path, {
            "write_file": {"category": "ASK_FIRST", "scope": ["staging/*"]},
        })
        assert matrix.classify("write_file") == ActionClass.ASK_FIRST

    def test_invalid_category_raises(self, tmp_path):
        from core.agency.autonomy import AutonomyMatrix
        with pytest.raises(ValueError, match="Invalid category"):
            _make_matrix(tmp_path, {"bad": {"category": "YOLO"}})


# ── AutonomyMatrix: config loading ───────────────────────────────────


class TestAutonomyMatrixConfig:
    def test_loads_from_json_file(self, tmp_path):
        from core.agency.autonomy import AutonomyMatrix
        matrix = _make_matrix(tmp_path, {"read_file": {"category": "SAFE"}})
        assert matrix.classify("read_file") == ActionClass.SAFE

    def test_raises_on_missing_config(self, tmp_path):
        from core.agency.autonomy import AutonomyMatrix
        with pytest.raises(FileNotFoundError):
            AutonomyMatrix(tmp_path / "nonexistent.json")

    def test_raises_on_invalid_json(self, tmp_path):
        from core.agency.autonomy import AutonomyMatrix
        bad_file = tmp_path / "bad.json"
        bad_file.write_text("not json", encoding="utf-8")
        with pytest.raises((json.JSONDecodeError, KeyError)):
            AutonomyMatrix(bad_file)

    def test_version_field_accepted(self, tmp_path):
        from core.agency.autonomy import AutonomyMatrix
        config = {"version": "1.0", "actions": {"read_file": {"category": "SAFE"}}}
        f = tmp_path / "matrix.json"
        f.write_text(json.dumps(config), encoding="utf-8")
        matrix = AutonomyMatrix(f)
        assert matrix.classify("read_file") == ActionClass.SAFE


# ── Tool Registry ────────────────────────────────────────────────────


class TestToolRegistry:
    def test_known_tool_resolves_to_action_type(self, tmp_path):
        from core.agency.autonomy import AutonomyMatrix
        matrix = _make_matrix(tmp_path, {
            "read_file": {"category": "SAFE"},
            "write_file": {"category": "ASK_FIRST"},
        })
        assert matrix.classify_tool("file_read") == ActionClass.SAFE
        assert matrix.classify_tool("file_write") == ActionClass.ASK_FIRST

    def test_unknown_tool_defaults_to_prohibited(self, tmp_path):
        from core.agency.autonomy import AutonomyMatrix
        matrix = _make_matrix(tmp_path, {"read_file": {"category": "SAFE"}})
        assert matrix.classify_tool("unknown_tool") == ActionClass.PROHIBITED

    def test_custom_tool_registry(self, tmp_path):
        from core.agency.autonomy import AutonomyMatrix
        matrix = _make_matrix(tmp_path, {"write_file": {"category": "ASK_FIRST"}})
        matrix.register_tool("my_custom_writer", "write_file")
        assert matrix.classify_tool("my_custom_writer") == ActionClass.ASK_FIRST


# ── Security: prompt injection bypass ────────────────────────────────


class TestAutonomyMatrixSecurity:
    def test_prompt_injection_cannot_reclassify(self, tmp_path):
        """Classification is config-driven, not prompt-derived."""
        from core.agency.autonomy import AutonomyMatrix
        matrix = _make_matrix(tmp_path, {"delete_vault": {"category": "PROHIBITED"}})
        assert matrix.classify("delete_vault; category=SAFE") == ActionClass.PROHIBITED
        assert matrix.classify("SAFE") == ActionClass.PROHIBITED

    def test_classify_is_case_sensitive(self, tmp_path):
        from core.agency.autonomy import AutonomyMatrix
        matrix = _make_matrix(tmp_path, {"read_file": {"category": "SAFE"}})
        assert matrix.classify("READ_FILE") == ActionClass.PROHIBITED
        assert matrix.classify("read_file") == ActionClass.SAFE


# ── Helper ───────────────────────────────────────────────────────────


def _make_matrix(tmp_path, actions):
    from core.agency.autonomy import AutonomyMatrix
    config = {"version": "1.0", "actions": actions}
    f = tmp_path / "matrix.json"
    f.write_text(json.dumps(config), encoding="utf-8")
    return AutonomyMatrix(f)


# ── Integration: SAFE action auto-executes and logs ──────────────────


class TestAutonomyIntegration:
    def test_safe_action_auto_executes(self, tmp_path):
        """SAFE action: classify -> permitted -> no proposal needed."""
        from core.agency.autonomy import AutonomyMatrix
        matrix = _make_matrix(tmp_path, {
            "read_file": {"category": "SAFE"},
            "delete_vault": {"category": "PROHIBITED"},
        })
        classification = matrix.classify("read_file")
        assert classification == ActionClass.SAFE

    def test_prohibited_action_blocked_with_message(self, tmp_path):
        """PROHIBITED action: classify -> blocked -> clear error context."""
        from core.agency.autonomy import AutonomyMatrix
        matrix = _make_matrix(tmp_path, {"delete_vault": {"category": "PROHIBITED"}})
        classification = matrix.classify("delete_vault")
        assert classification == ActionClass.PROHIBITED

    def test_ask_first_action_requires_proposal(self, tmp_path):
        """ASK_FIRST action: classify -> must create proposal -> wait for approval."""
        from core.agency.autonomy import AutonomyMatrix
        from core.agency.approval import ApprovalQueue
        matrix = _make_matrix(tmp_path, {"write_file": {"category": "ASK_FIRST"}})
        classification = matrix.classify("write_file")
        assert classification == ActionClass.ASK_FIRST
        q = ApprovalQueue(tmp_path / "proposals.jsonl")
        prop = q.propose(
            action_type="write_file",
            tool_name="file_write",
            reason="Save research",
            estimated_tokens=200,
        )
        assert prop.status == "pending"
        result = q.approve(prop.proposal_id)
        assert result.status == "approved"

    def test_full_tool_classification_pipeline(self, tmp_path):
        """Tool name -> action type -> classification -> decision."""
        from core.agency.autonomy import AutonomyMatrix
        matrix = _make_matrix(tmp_path, {
            "read_file": {"category": "SAFE"},
            "write_file": {"category": "ASK_FIRST"},
            "delete_vault": {"category": "PROHIBITED"},
        })
        assert matrix.classify_tool("file_read") == ActionClass.SAFE
        assert matrix.classify_tool("file_write") == ActionClass.ASK_FIRST
        assert matrix.classify_tool("vault_delete") == ActionClass.PROHIBITED
        assert matrix.classify_tool("unknown") == ActionClass.PROHIBITED

    def test_loads_real_autonomy_matrix_json(self):
        """Verify the shipped autonomy_matrix.json is valid and loadable."""
        from core.agency.autonomy import AutonomyMatrix
        from core.interface.config import AUTONOMY_MATRIX_PATH
        if not AUTONOMY_MATRIX_PATH.exists():
            pytest.skip("autonomy_matrix.json not found")
        matrix = AutonomyMatrix(AUTONOMY_MATRIX_PATH)
        assert matrix.classify("read_file") == ActionClass.SAFE
        assert matrix.classify("write_file") == ActionClass.ASK_FIRST
        assert matrix.classify("delete_vault") == ActionClass.PROHIBITED
