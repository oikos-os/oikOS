"""JSONL research queue — add, list, remove, pop topics."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

_PRIORITY_ORDER = {"high": 0, "normal": 1, "low": 2}
_DEFAULT_PATH = Path("logs/research/queue.jsonl")


class ResearchQueue:
    def __init__(self, path: Path | None = None):
        self._path = path or _DEFAULT_PATH
        self._items: list[dict] = []
        self._load()

    def _load(self) -> None:
        if self._path.exists():
            for line in self._path.read_text(encoding="utf-8").strip().split("\n"):
                if line.strip():
                    self._items.append(json.loads(line))

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            for item in self._items:
                f.write(json.dumps(item) + "\n")
        os.replace(tmp, self._path)

    def _next_id(self) -> str:
        existing = [int(i["id"].split("-")[1]) for i in self._items if i["id"].startswith("r-")]
        return f"r-{max(existing, default=0) + 1:03d}"

    def add(self, topic: str, priority: str = "normal") -> dict:
        item = {
            "id": self._next_id(),
            "topic": topic,
            "priority": priority if priority in _PRIORITY_ORDER else "normal",
            "status": "pending",
            "added": datetime.now(timezone.utc).isoformat(),
            "processed": None,
        }
        self._items.append(item)
        self._save()
        return item

    def list(self, include_removed: bool = False) -> list[dict]:
        items = self._items if include_removed else [i for i in self._items if i["status"] not in ("removed",)]
        return sorted(items, key=lambda i: (_PRIORITY_ORDER.get(i["priority"], 1), i["added"]))

    def remove(self, item_id: str) -> dict | None:
        for item in self._items:
            if item["id"] == item_id:
                item["status"] = "removed"
                self._save()
                return item
        return None

    def pop(self, count: int = 1) -> list[dict]:
        pending = [i for i in self.list() if i["status"] == "pending"]
        popped = pending[:count]
        for item in popped:
            item["status"] = "processing"
        if popped:
            self._save()
        return popped

    def complete(self, item_id: str) -> None:
        for item in self._items:
            if item["id"] == item_id:
                item["status"] = "completed"
                item["processed"] = datetime.now(timezone.utc).isoformat()
                self._save()
                return

    def revert(self, item_id: str) -> None:
        for item in self._items:
            if item["id"] == item_id:
                item["status"] = "pending"
                self._save()
                return
