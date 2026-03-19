"""Tests for ResearchAgent coordinator."""

import pytest
from core.agency.research import ResearchAgent


class TestResearchAgent:
    def test_has_queue(self, tmp_path):
        agent = ResearchAgent(queue_path=tmp_path / "q.jsonl", staging_dir=tmp_path / "staging")
        assert agent.queue is not None

    def test_has_runner(self, tmp_path):
        agent = ResearchAgent(queue_path=tmp_path / "q.jsonl", staging_dir=tmp_path / "staging")
        assert agent.runner is not None

    def test_has_reviewer(self, tmp_path):
        agent = ResearchAgent(queue_path=tmp_path / "q.jsonl", staging_dir=tmp_path / "staging")
        assert agent.reviewer is not None

    def test_queue_add_and_list(self, tmp_path):
        agent = ResearchAgent(queue_path=tmp_path / "q.jsonl", staging_dir=tmp_path / "staging")
        agent.queue.add("test topic")
        items = agent.queue.list()
        assert len(items) == 1
