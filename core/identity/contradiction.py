"""NLI contradiction check — verify response against vault chunks."""

from __future__ import annotations

import json
import logging

from core.interface.models import ContradictionResult

log = logging.getLogger(__name__)

_NLI_PROMPT = """ESTABLISHED FACTS (from vault):
{chunks}

RESPONSE TO CHECK:
{response}

Does the response contradict any established fact?
Return JSON only: {{"has_contradiction": bool, "contradiction_type": "identity"|"knowledge"|"none", "confidence": 0-100, "explanation": "..."}}"""


def check_contradiction(
    response_text: str,
    vault_chunks: list[dict],
) -> ContradictionResult:
    """NLI check: does response contradict vault chunks?

    Sends structured prompt to cloud. Parses JSON response.
    On failure (cloud unreachable), returns clean result — graceful degradation.
    """
    if not vault_chunks:
        return ContradictionResult(
            has_contradiction=False,
            contradiction_type="none",
            confidence=0.0,
            explanation="No vault chunks to compare",
        )

    # Format chunks (max 5)
    formatted = []
    for c in vault_chunks[:5]:
        formatted.append(f"[{c['source_path']}]\n{c['content']}")
    chunks_text = "\n\n".join(formatted)

    prompt = _NLI_PROMPT.format(chunks=chunks_text, response=response_text)

    try:
        from core.cognition.cloud import send_to_cloud

        cloud_resp = send_to_cloud(
            query=prompt,
            context="",
            model=None,
        )

        # Parse JSON from response
        raw_text = cloud_resp.text.strip()
        # Handle markdown code blocks
        if raw_text.startswith("```"):
            raw_text = raw_text.split("\n", 1)[1].rsplit("```", 1)[0].strip()

        data = json.loads(raw_text)
        return ContradictionResult(
            has_contradiction=data.get("has_contradiction", False),
            contradiction_type=data.get("contradiction_type", "none"),
            confidence=float(data.get("confidence", 0)),
            explanation=data.get("explanation", ""),
        )
    except json.JSONDecodeError as e:
        log.warning("NLI response not valid JSON: %s", e)
        return ContradictionResult(
            has_contradiction=False,
            contradiction_type="none",
            confidence=0.0,
            explanation=f"JSON parse error: {e}",
        )
    except Exception as e:
        log.warning("NLI check failed: %s", e)
        return ContradictionResult(
            has_contradiction=False,
            contradiction_type="none",
            confidence=0.0,
            explanation=f"Cloud unavailable: {e}",
        )
