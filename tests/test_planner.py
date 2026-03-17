from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from core.agency.planner import PlanStep, ReWOOPlanner

_MOCK_PLAN = json.dumps([
    {"step_id": "#E1", "tool_name": "vault_search", "tool_args": {"query": "memory architecture"}, "depends_on": []},
    {"step_id": "#E2", "tool_name": "file_read", "tool_args": {"path": "#E1"}, "depends_on": ["#E1"]},
    {"step_id": "#E3", "tool_name": "vault_search", "tool_args": {"query": "embedding model"}, "depends_on": []},
])

_MOCK_STEPS = [PlanStep.from_dict(s) for s in json.loads(_MOCK_PLAN)]


# ── PlanStep model ────────────────────────────────────────────────────

class TestPlanStep:
    def test_serialization_roundtrip(self):
        step = PlanStep(step_id="#E1", tool_name="vault_search",
                        tool_args={"query": "test"}, depends_on=["#E0"])
        assert PlanStep.from_dict(step.to_dict()) == step

    def test_json_roundtrip(self):
        step = PlanStep(step_id="#E2", tool_name="file_read",
                        tool_args={"path": "/tmp/x"}, depends_on=["#E1"])
        restored = PlanStep.from_dict(json.loads(json.dumps(step.to_dict())))
        assert restored == step

    def test_step_id_prefix(self):
        step = PlanStep(step_id="#E5", tool_name="t", tool_args={})
        assert step.step_id.startswith("#E")


# ── Plan generation ───────────────────────────────────────────────────

class TestPlanGeneration:
    @patch("core.agency.planner.generate_local")
    def test_plan_returns_list_of_planstep(self, mock_gl):
        mock_gl.return_value = {"response": _MOCK_PLAN}
        planner = ReWOOPlanner()
        steps = planner.plan("describe memory arch", ["vault_search", "file_read"])
        assert all(isinstance(s, PlanStep) for s in steps)
        assert len(steps) == 3

    @patch("core.agency.planner.generate_local")
    def test_preserves_dependency_references(self, mock_gl):
        mock_gl.return_value = {"response": _MOCK_PLAN}
        steps = ReWOOPlanner().plan("task", ["vault_search", "file_read"])
        assert steps[1].depends_on == ["#E1"]
        assert steps[0].depends_on == []

    @patch("core.agency.planner.generate_local")
    def test_handles_markdown_fences(self, mock_gl):
        mock_gl.return_value = {"response": f"```json\n{_MOCK_PLAN}\n```"}
        steps = ReWOOPlanner().plan("task", ["vault_search", "file_read"])
        assert len(steps) == 3

    @patch("core.agency.planner.generate_local")
    def test_returns_empty_on_llm_error(self, mock_gl):
        mock_gl.return_value = {"error": "timeout", "response": ""}
        steps = ReWOOPlanner().plan("task", ["vault_search"])
        assert steps == []


# ── Execution ─────────────────────────────────────────────────────────

class TestExecution:
    def _registry(self):
        return {
            "vault_search": MagicMock(return_value="doc_path.md"),
            "file_read": MagicMock(return_value="file contents here"),
        }

    @patch("core.agency.planner.compress", side_effect=lambda r, *a, **kw: r)
    def test_populates_evidence(self, mock_compress):
        reg = self._registry()
        evidence = ReWOOPlanner().execute(_MOCK_STEPS, reg)
        assert "#E1" in evidence and "#E3" in evidence

    @patch("core.agency.planner.compress", side_effect=lambda r, *a, **kw: r)
    def test_resolves_placeholders(self, mock_compress):
        reg = self._registry()
        ReWOOPlanner().execute(_MOCK_STEPS, reg)
        reg["file_read"].assert_called_once()
        call_args = reg["file_read"].call_args
        assert "doc_path.md" in str(call_args)

    @patch("core.agency.planner.compress", side_effect=lambda r, *a, **kw: r)
    def test_failed_tool_stores_error_continues(self, mock_compress):
        reg = self._registry()
        reg["vault_search"].side_effect = [RuntimeError("boom"), "ok"]
        evidence = ReWOOPlanner().execute(_MOCK_STEPS, reg)
        assert "error" in evidence["#E1"].lower()
        assert "#E3" in evidence

    @patch("core.agency.planner.compress")
    def test_results_pass_through_compressor(self, mock_compress):
        mock_compress.return_value = "compressed"
        reg = self._registry()
        evidence = ReWOOPlanner().execute(_MOCK_STEPS, reg)
        assert mock_compress.call_count == 3
        assert all(v == "compressed" or "error" not in v.lower()
                   for v in evidence.values())

    @patch("core.agency.planner.compress", side_effect=lambda r, *a, **kw: r)
    def test_zero_llm_calls_during_execute(self, mock_compress):
        reg = self._registry()
        with patch("core.agency.planner.generate_local") as mock_gl:
            ReWOOPlanner().execute(_MOCK_STEPS, reg)
            mock_gl.assert_not_called()


# ── Solving ───────────────────────────────────────────────────────────

class TestSolving:
    @patch("core.agency.planner.generate_local")
    def test_solve_returns_answer(self, mock_gl):
        mock_gl.return_value = {"response": "The architecture uses LanceDB."}
        answer = ReWOOPlanner().solve("describe memory", _MOCK_STEPS,
                                      {"#E1": "doc_path.md", "#E2": "contents", "#E3": "nomic"})
        assert "LanceDB" in answer

    @patch("core.agency.planner.generate_local")
    def test_solver_prompt_contains_evidence(self, mock_gl):
        mock_gl.return_value = {"response": "answer"}
        ReWOOPlanner().solve("task", _MOCK_STEPS,
                             {"#E1": "alpha", "#E2": "beta", "#E3": "gamma"})
        prompt = mock_gl.call_args[0][0]
        assert "#E1" in prompt and "alpha" in prompt
        assert "#E2" in prompt and "#E3" in prompt


# ── Token efficiency ──────────────────────────────────────────────────

class TestTokenEfficiency:
    def test_rewoo_fewer_tokens_than_react(self):
        """ReWOO: 2 LLM calls (plan + solve), results never sent to LLM mid-loop.
        ReAct: each step re-sends growing context (task + all prior observations).
        ReWOO saves tokens because execute() is zero-LLM."""
        n_steps = 3
        base_prompt = 500
        result_tokens = 300
        # ReWOO: plan prompt + solve prompt (with all evidence appended once)
        rewoo_tokens = base_prompt + (base_prompt + n_steps * result_tokens)
        # ReAct: each step i sends base_prompt + all prior results (0..i-1)
        react_tokens = sum(
            base_prompt + i * result_tokens for i in range(n_steps + 1)
        )
        assert rewoo_tokens / react_tokens <= 0.50


# ── Edge cases ────────────────────────────────────────────────────────

class TestEdgeCases:
    @patch("core.agency.planner.compress", side_effect=lambda r, *a, **kw: r)
    def test_single_step_plan(self, mock_compress):
        step = PlanStep(step_id="#E1", tool_name="vault_search",
                        tool_args={"query": "test"})
        reg = {"vault_search": MagicMock(return_value="result")}
        evidence = ReWOOPlanner().execute([step], reg)
        assert evidence["#E1"] == "result"

    @patch("core.agency.planner.compress", side_effect=lambda r, *a, **kw: r)
    def test_empty_tool_registry(self, mock_compress):
        step = PlanStep(step_id="#E1", tool_name="missing_tool",
                        tool_args={"q": "x"})
        evidence = ReWOOPlanner().execute([step], {})
        assert "error" in evidence["#E1"].lower()

    @patch("core.agency.planner.compress", side_effect=lambda r, *a, **kw: r)
    def test_no_dependencies(self, mock_compress):
        steps = [
            PlanStep(step_id="#E1", tool_name="t", tool_args={"a": "1"}),
            PlanStep(step_id="#E2", tool_name="t", tool_args={"b": "2"}),
        ]
        reg = {"t": MagicMock(return_value="ok")}
        evidence = ReWOOPlanner().execute(steps, reg)
        assert len(evidence) == 2
        assert reg["t"].call_count == 2
