from __future__ import annotations

import json
import logging
import re

from core.agency.context_engine import estimate_tokens
from core.interface.config import (
    COMPRESSOR_ARRAY_PREVIEW_COUNT,
    COMPRESSOR_MAX_OUTPUT_TOKENS,
    COMPRESSOR_MODEL,
    COMPRESSOR_THRESHOLD_TOKENS,
)

log = logging.getLogger(__name__)

_CLIXML_RE = re.compile(r"#<\s*CLIXML.*?</Objs>", re.DOTALL | re.IGNORECASE)
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_MULTI_NEWLINE_RE = re.compile(r"\n{3,}")
_LARGE_NUMBER_RE = re.compile(r"\b(\d{1,3}(?:,?\d{3})+)\b")

generate_local = None  # lazy-loaded


def _ensure_generate_local():
    global generate_local
    if generate_local is None:
        from core.cognition.inference import generate_local as _gl
        generate_local = _gl


def _strip_nulls(obj):
    if isinstance(obj, dict):
        return {k: _strip_nulls(v) for k, v in obj.items()
                if v is not None and v != ""}
    if isinstance(obj, list):
        return [_strip_nulls(item) for item in obj]
    return obj


def _truncate_array(arr: list, preview: int = COMPRESSOR_ARRAY_PREVIEW_COUNT) -> list:
    if len(arr) <= preview:
        return arr
    return arr[:preview] + [f"[...{preview} of {len(arr)} items shown]"]


def _truncate_arrays(obj, preview: int = COMPRESSOR_ARRAY_PREVIEW_COUNT):
    if isinstance(obj, dict):
        return {k: _truncate_arrays(v, preview) for k, v in obj.items()}
    if isinstance(obj, list):
        truncated = _truncate_array(obj, preview)
        return [_truncate_arrays(item, preview) for item in truncated]
    return obj


def _abbreviate_number(match: re.Match) -> str:
    raw = match.group(1).replace(",", "")
    n = int(raw)
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return match.group(0)


class RuleCompressor:
    @staticmethod
    def compress(text: str) -> str:
        text = _CLIXML_RE.sub("", text)

        is_json = False
        try:
            data = json.loads(text)
            data = _strip_nulls(data)
            data = _truncate_arrays(data)
            text = json.dumps(data, separators=(",", ":"))
            is_json = True
        except (json.JSONDecodeError, TypeError):
            pass

        text = _HTML_TAG_RE.sub("", text)
        if not is_json:
            text = _LARGE_NUMBER_RE.sub(_abbreviate_number, text)
        text = _MULTI_NEWLINE_RE.sub("\n\n", text)
        return text.strip()


class LLMCompressor:
    @staticmethod
    def compress(text: str, task_context: str, max_tokens: int = COMPRESSOR_MAX_OUTPUT_TOKENS) -> str:
        _ensure_generate_local()
        try:
            prompt = (
                f"Extract only the information relevant to '{task_context}' "
                f"from this result. Be concise.\n\n{text}"
            )
            resp = generate_local(
                prompt, model=COMPRESSOR_MODEL, num_predict=max_tokens
            )
            result = resp.get("response", "").strip()
            if not result:
                raise ValueError("empty LLM response")
        except Exception:
            log.warning("LLM compression failed, falling back to truncation")
            words = text.split()
            target_words = int(max_tokens / 1.3)
            return " ".join(words[:target_words])

        if estimate_tokens(result) > max_tokens:
            words = result.split()
            target_words = int(max_tokens / 1.3)
            result = " ".join(words[:target_words])
        return result


def compress(
    tool_result: str,
    task_context: str,
    threshold: int = COMPRESSOR_THRESHOLD_TOKENS,
) -> str:
    result = RuleCompressor.compress(tool_result)
    if estimate_tokens(result) > threshold:
        result = LLMCompressor.compress(result, task_context)
    return result
