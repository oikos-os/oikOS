"""Research runner — search → fetch → summarize → stage pipeline."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

from core.agency.research.dedup import is_duplicate
from core.cognition.inference import generate_local
from core.framework.tools.browser_tools import _validate_url, web_fetch, web_search

_STAGING_DIR = Path("staging/research")
_SYSTEM_PROMPT = "Summarize the following web content about {topic}. Extract key facts, findings, and actionable information. Be concise."


class ResearchRunner:
    def __init__(self, staging_dir: Path | None = None):
        self._staging_dir = staging_dir or _STAGING_DIR

    async def run_topic(self, topic: str, max_results: int = 3) -> dict:
        search_result = await web_search(topic, count=max_results)
        if "status" in search_result and search_result["status"] == "error":
            return {"staged": False, "error": search_result["message"], "tokens_used": 0}

        urls = [r["url"] for r in search_result.get("results", [])][:max_results]
        if not urls:
            return {"staged": False, "error": "No search results", "tokens_used": 0}

        fetched_content = []
        sources = []
        tokens_used = 0
        for url in urls:
            try:
                _validate_url(url)
            except ValueError:
                continue
            result = await web_fetch(url, max_tokens=3000)
            if "status" in result and result["status"] == "error":
                continue
            content = result.get("content", "")
            tokens_used += len(content) // 4
            fetched_content.append(content)
            sources.append(url)

        if not fetched_content:
            return {"staged": False, "error": "All fetches failed", "tokens_used": tokens_used}

        combined = "\n\n---\n\n".join(fetched_content)
        try:
            summary_result = generate_local(
                combined[:8000],
                system=_SYSTEM_PROMPT.format(topic=topic),
                model="qwen2.5:7b",
            )
            summary = summary_result.get("response", "")
            tokens_used += len(summary) // 4
        except (ConnectionError, OSError, RuntimeError):
            return {"staged": False, "error": "Ollama unavailable", "tokens_used": tokens_used}

        if is_duplicate(topic):
            return {"staged": False, "skipped_duplicate": True, "tokens_used": tokens_used}

        self._stage(topic, summary, sources, tokens_used)
        return {"staged": True, "skipped_duplicate": False, "tokens_used": tokens_used, "sources": sources}

    def _stage(self, topic: str, summary: str, sources: list[str], tokens_used: int) -> Path:
        self._staging_dir.mkdir(parents=True, exist_ok=True)
        now = datetime.now(timezone.utc)
        safe_topic = re.sub(r"[^\w\s-]", "", topic).strip().replace(" ", "_")[:50]
        filename = f"{safe_topic}_{now.strftime('%Y%m%d_%H%M%S')}.md"
        path = self._staging_dir / filename

        sources_yaml = "\n".join(f"  - {s}" for s in sources)
        frontmatter = f"""---
topic: {topic}
sources:
{sources_yaml}
tokens_used: {tokens_used}
created: {now.isoformat()}
tier: semantic
domain: RESEARCH
status: staged
updated: {now.strftime('%Y-%m-%d')}
---"""

        path.write_text(f"{frontmatter}\n\n# {topic}\n\n{summary}\n", encoding="utf-8")
        return path
