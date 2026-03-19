"""Research MCP tools — queue, run, review, approve, reject."""

from core.framework import oikos_tool, PrivacyTier, AutonomyLevel

_agent = None


def _get_agent():
    global _agent
    if _agent is None:
        from core.agency.research import ResearchAgent
        _agent = ResearchAgent()
    return _agent


@oikos_tool(
    name="oikos_research_queue",
    description="Manage the research queue — list, add, or remove topics",
    privacy=PrivacyTier.SAFE,
    autonomy=AutonomyLevel.SAFE,
    toolset="research",
)
def research_queue(action: str = "list", topic: str = "", priority: str = "normal") -> dict:
    agent = _get_agent()
    if action == "add":
        if not topic:
            return {"status": "error", "message": "Topic required for 'add' action"}
        item = agent.queue.add(topic, priority=priority)
        return {"action": "add", "items": [item], "count": 1}
    elif action == "remove":
        if not topic:
            return {"status": "error", "message": "Topic ID required for 'remove' action"}
        result = agent.queue.remove(topic)
        if result is None:
            return {"status": "error", "message": f"Item not found: {topic}"}
        return {"action": "remove", "items": [result], "count": 1}
    else:
        items = agent.queue.list()
        return {"action": "list", "items": items, "count": len(items)}


@oikos_tool(
    name="oikos_research_run",
    description="Execute a research cycle — search, fetch, summarize, and stage results for review",
    privacy=PrivacyTier.SENSITIVE,
    autonomy=AutonomyLevel.ASK_FIRST,
    toolset="research",
)
async def research_run(max_topics: int = 3, max_results_per_topic: int = 3, token_budget: int = 50000) -> dict:
    agent = _get_agent()
    topics = agent.queue.pop(count=max_topics)
    if not topics:
        return {"topics_processed": 0, "results_staged": 0, "tokens_used": 0,
                "budget_remaining": token_budget, "skipped_duplicates": 0, "message": "Queue empty"}

    total_tokens = 0
    staged = 0
    skipped = 0
    for topic_item in topics:
        if total_tokens >= token_budget:
            break
        try:
            result = await agent.runner.run_topic(topic_item["topic"], max_results=max_results_per_topic)
        except Exception:
            agent.queue.revert(topic_item["id"])
            continue
        total_tokens += result.get("tokens_used", 0)
        if result.get("staged"):
            staged += 1
            agent.queue.complete(topic_item["id"])
        elif result.get("skipped_duplicate"):
            skipped += 1
            agent.queue.complete(topic_item["id"])

    return {
        "topics_processed": len(topics),
        "results_staged": staged,
        "tokens_used": total_tokens,
        "budget_remaining": token_budget - total_tokens,
        "skipped_duplicates": skipped,
    }


@oikos_tool(
    name="oikos_research_review",
    description="List all staged research results awaiting Architect review",
    privacy=PrivacyTier.SAFE,
    autonomy=AutonomyLevel.SAFE,
    toolset="research",
)
def research_review() -> dict:
    agent = _get_agent()
    return agent.reviewer.list_staged()


@oikos_tool(
    name="oikos_research_approve",
    description="Promote staged research to the vault (direct copy + reindex)",
    privacy=PrivacyTier.NEVER_LEAVE,
    autonomy=AutonomyLevel.ASK_FIRST,
    toolset="research",
)
def research_approve(filename: str, vault_tier: str = "semantic", domain: str = "RESEARCH") -> dict:
    agent = _get_agent()
    return agent.reviewer.approve(filename, vault_tier=vault_tier, domain=domain)


@oikos_tool(
    name="oikos_research_reject",
    description="Delete staged research results (single file or all)",
    privacy=PrivacyTier.SAFE,
    autonomy=AutonomyLevel.SAFE,
    toolset="research",
)
def research_reject(filename: str = "") -> dict:
    agent = _get_agent()
    if not filename:
        return agent.reviewer.reject_all()
    return agent.reviewer.reject(filename)
