"""Shared text utilities."""

from __future__ import annotations


def strip_markdown_fences(text: str) -> str:
    """Strip markdown ```json / ``` fences from LLM responses.

    Handles common patterns:
    - ```json ... ```
    - ``` ... ```
    """
    text = text.strip()
    if text.startswith("```json"):
        text = text[7:]
    if text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    return text.strip()
