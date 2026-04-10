"""Research agency — autonomous research for oikOS IDLE state.

ResearchAgent is the coordinator. All tools go through it.
"""

from __future__ import annotations

from pathlib import Path

from core.agency.research.queue import ResearchQueue
from core.agency.research.runner import ResearchRunner
from core.agency.research.reviewer import ResearchReviewer

_DEFAULT_QUEUE = Path("logs/research/queue.jsonl")
_DEFAULT_STAGING = Path("staging/research")


class ResearchAgent:
    def __init__(
        self,
        queue_path: Path | None = None,
        staging_dir: Path | None = None,
    ):
        self.queue = ResearchQueue(path=queue_path or _DEFAULT_QUEUE)
        self.runner = ResearchRunner(staging_dir=staging_dir or _DEFAULT_STAGING)
        self.reviewer = ResearchReviewer(staging_dir=staging_dir or _DEFAULT_STAGING)
