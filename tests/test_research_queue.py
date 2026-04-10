"""Tests for research JSONL queue."""

import json
import pytest
from core.agency.research.queue import ResearchQueue


class TestResearchQueue:
    def test_add_creates_item(self, tmp_path):
        q = ResearchQueue(path=tmp_path / "queue.jsonl")
        result = q.add("MCP protocol", priority="high")
        assert result["topic"] == "MCP protocol"
        assert result["priority"] == "high"
        assert result["status"] == "pending"
        assert result["id"].startswith("r-")

    def test_add_persists_to_file(self, tmp_path):
        path = tmp_path / "queue.jsonl"
        q = ResearchQueue(path=path)
        q.add("topic 1")
        assert path.exists()
        lines = path.read_text().strip().split("\n")
        assert len(lines) == 1
        assert json.loads(lines[0])["topic"] == "topic 1"

    def test_list_returns_pending_items(self, tmp_path):
        q = ResearchQueue(path=tmp_path / "queue.jsonl")
        q.add("topic 1")
        q.add("topic 2")
        items = q.list()
        assert len(items) == 2

    def test_list_excludes_removed(self, tmp_path):
        q = ResearchQueue(path=tmp_path / "queue.jsonl")
        item = q.add("topic 1")
        q.add("topic 2")
        q.remove(item["id"])
        items = q.list()
        assert len(items) == 1
        assert items[0]["topic"] == "topic 2"

    def test_remove_soft_deletes(self, tmp_path):
        q = ResearchQueue(path=tmp_path / "queue.jsonl")
        item = q.add("topic 1")
        q.remove(item["id"])
        all_items = q.list(include_removed=True)
        removed = [i for i in all_items if i["status"] == "removed"]
        assert len(removed) == 1

    def test_priority_ordering(self, tmp_path):
        q = ResearchQueue(path=tmp_path / "queue.jsonl")
        q.add("low topic", priority="low")
        q.add("high topic", priority="high")
        q.add("normal topic", priority="normal")
        items = q.list()
        assert items[0]["topic"] == "high topic"
        assert items[1]["topic"] == "normal topic"
        assert items[2]["topic"] == "low topic"

    def test_pop_returns_highest_priority(self, tmp_path):
        q = ResearchQueue(path=tmp_path / "queue.jsonl")
        q.add("low", priority="low")
        q.add("high", priority="high")
        popped = q.pop(count=1)
        assert len(popped) == 1
        assert popped[0]["topic"] == "high"
        assert popped[0]["status"] == "processing"

    def test_pop_marks_as_processing(self, tmp_path):
        q = ResearchQueue(path=tmp_path / "queue.jsonl")
        q.add("topic")
        q.pop(count=1)
        pending = [i for i in q.list() if i["status"] == "pending"]
        assert len(pending) == 0

    def test_complete_marks_done(self, tmp_path):
        q = ResearchQueue(path=tmp_path / "queue.jsonl")
        item = q.add("topic")
        q.pop(count=1)
        q.complete(item["id"])
        all_items = q.list(include_removed=True)
        completed = [i for i in all_items if i["status"] == "completed"]
        assert len(completed) == 1

    def test_remove_nonexistent_returns_none(self, tmp_path):
        q = ResearchQueue(path=tmp_path / "queue.jsonl")
        result = q.remove("r-nonexistent")
        assert result is None

    def test_empty_queue_pop_returns_empty(self, tmp_path):
        q = ResearchQueue(path=tmp_path / "queue.jsonl")
        popped = q.pop(count=3)
        assert popped == []
