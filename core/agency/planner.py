from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field

from core.agency.compressor import compress
from core.interface.config import COMPRESSOR_MODEL

log = logging.getLogger(__name__)
generate_local = None  # lazy-loaded
_PLACEHOLDER_RE = re.compile(r"#E\d+")
_FENCE_RE = re.compile(r"```(?:json)?\s*\n?(.*?)\n?\s*```", re.DOTALL)


def _ensure_generate_local():
    global generate_local
    if generate_local is None:
        from core.cognition.inference import generate_local as _gl
        generate_local = _gl


def _strip_markdown_fences(text: str) -> str:
    m = _FENCE_RE.search(text)
    return m.group(1).strip() if m else text.strip()


def _resolve_placeholders(value, evidence: dict[str, str]):
    if isinstance(value, str):
        for ref in _PLACEHOLDER_RE.findall(value):
            if ref in evidence:
                value = value.replace(ref, evidence[ref])
    elif isinstance(value, dict):
        return {k: _resolve_placeholders(v, evidence) for k, v in value.items()}
    elif isinstance(value, list):
        return [_resolve_placeholders(item, evidence) for item in value]
    return value


@dataclass
class PlanStep:
    step_id: str
    tool_name: str
    tool_args: dict
    depends_on: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"step_id": self.step_id, "tool_name": self.tool_name,
                "tool_args": self.tool_args, "depends_on": self.depends_on}

    @classmethod
    def from_dict(cls, data: dict) -> PlanStep:
        return cls(step_id=data["step_id"], tool_name=data["tool_name"],
                   tool_args=data["tool_args"],
                   depends_on=data.get("depends_on", []))


class ReWOOPlanner:
    def plan(self, task: str, available_tools: list[str]) -> list[PlanStep]:
        _ensure_generate_local()
        prompt = (
            f"Task: {task}\n"
            f"Available tools: {', '.join(available_tools)}\n\n"
            "Create a plan as a JSON array. Each element has: "
            "step_id (#E1, #E2, ...), tool_name, tool_args (dict), "
            "depends_on (list of step_ids). Use #E references in tool_args "
            "to reference earlier results. Return ONLY the JSON array."
        )
        try:
            resp = generate_local(prompt, model=COMPRESSOR_MODEL)
            raw = resp.get("response", "")
            if not raw:
                return []
            parsed = json.loads(_strip_markdown_fences(raw))
            return [PlanStep.from_dict(s) for s in parsed]
        except Exception:
            log.warning("Plan generation failed", exc_info=True)
            return []

    def execute(self, steps: list[PlanStep],
                tool_registry: dict[str, callable]) -> dict[str, str]:
        evidence: dict[str, str] = {}
        for step in steps:
            if step.tool_name not in tool_registry:
                evidence[step.step_id] = f"[Error] Tool '{step.tool_name}' not found"
                continue
            try:
                resolved_args = _resolve_placeholders(step.tool_args, evidence)
                result = str(tool_registry[step.tool_name](**resolved_args))
                evidence[step.step_id] = compress(result, step.tool_name)
            except Exception as exc:
                evidence[step.step_id] = f"[Error] {exc}"
        return evidence

    def solve(self, task: str, plan: list[PlanStep],
              evidence: dict[str, str]) -> str:
        _ensure_generate_local()
        evidence_block = "\n".join(
            f"{s.step_id} ({s.tool_name}): {evidence.get(s.step_id, 'N/A')}"
            for s in plan
        )
        prompt = (
            f"Task: {task}\n\nEvidence:\n{evidence_block}\n\n"
            "Using the evidence above, provide a comprehensive answer to the task."
        )
        resp = generate_local(prompt, model=COMPRESSOR_MODEL)
        return resp.get("response", "")
