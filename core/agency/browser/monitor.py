"""Page change detection via content hashing."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from core.agency.browser.fetcher import WebFetcher


class PageMonitor:
    """Detects content changes on web pages by comparing content hashes."""

    def __init__(self, fetcher: WebFetcher, state_path: Path | None = None):
        self._fetcher = fetcher
        self._state_path = state_path or Path("logs/monitor_state.json")
        self._state = self._load_state()

    def _load_state(self) -> dict:
        if self._state_path.exists():
            return json.loads(self._state_path.read_text(encoding="utf-8"))
        return {}

    def _save_state(self) -> None:
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        self._state_path.write_text(json.dumps(self._state, indent=2), encoding="utf-8")

    async def check(self, url: str, selector: str = "") -> dict:
        result = await self._fetcher.fetch(url)
        if "status" in result and result["status"] == "error":
            return result

        content = result.get("content", "")
        content_hash = hashlib.sha256(content.encode()).hexdigest()
        now = datetime.now(timezone.utc).isoformat()

        prev = self._state.get(url)
        changed = False
        diff_summary = None

        if prev is not None:
            if prev["hash"] != content_hash:
                changed = True
                old_len = prev.get("length", 0)
                new_len = len(content)
                delta = new_len - old_len
                sign = "+" if delta >= 0 else ""
                diff_summary = f"Content changed: old_length={old_len}, new_length={new_len}, delta={sign}{delta} chars"

        self._state[url] = {"hash": content_hash, "length": len(content), "last_checked": now}
        self._save_state()

        return {"url": url, "changed": changed, "last_checked": now, "diff_summary": diff_summary}
