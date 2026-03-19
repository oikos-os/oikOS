"""Inference tools — local Ollama generation and full handler pipeline."""

from core.framework import oikos_tool, PrivacyTier, AutonomyLevel


@oikos_tool(
    name="oikos_ollama_generate",
    description="Generate a response using local Ollama inference (never leaves machine)",
    privacy=PrivacyTier.NEVER_LEAVE,
    autonomy=AutonomyLevel.SAFE,
    toolset="system",
    cost_category="local",
)
def ollama_generate(prompt: str, system: str = "", model: str = "") -> dict:
    from core.cognition.inference import generate_local
    result = generate_local(prompt, system=system or None, model=model or None)
    return {
        "response": result.get("response", ""),
        "model": result.get("model", ""),
        "eval_count": result.get("eval_count", 0),
    }


@oikos_tool(
    name="oikos_provider_query",
    description="Run a query through the full oikOS handler pipeline (PII, routing, inference, confidence)",
    privacy=PrivacyTier.SENSITIVE,
    autonomy=AutonomyLevel.SAFE,
    toolset="system",
    cost_category="cloud",
)
def provider_query(
    query: str,
    force_local: bool = False,
    force_cloud: bool = False,
    provider: str = "",
    model: str = "",
) -> dict:
    from core.cognition.handler import execute_query
    resp = execute_query(
        query,
        force_local=force_local,
        force_cloud=force_cloud,
        cloud_name=provider or None,
        model_override=model or None,
    )
    return {
        "text": resp.text,
        "model": resp.model_used,
        "route": resp.route,
        "confidence": resp.confidence,
        "pii_scrubbed": resp.pii_scrubbed,
    }
