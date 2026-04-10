"""Default Room configurations and templates."""

from __future__ import annotations

from core.rooms.models import RoomConfig


def home_room() -> RoomConfig:
    """The default Home Room — full access, all tools."""
    return RoomConfig(
        id="home",
        name="Home",
        description="Default room with full vault access and all tools.",
        vault_scope={"mode": "all"},
        toolsets=None,
        autonomy={},
        model={},
        voice={"personality": "You are a helpful general-purpose assistant with full access to all tools and vault."},
        limits={"session_isolation": False},
    )


TEMPLATES: dict[str, dict] = {
    "researcher": {
        "name": "Research",
        "description": "Deep research with browser and vault access.",
        "vault_scope": {"mode": "all"},
        "toolsets": ["vault", "browser", "research", "system"],
        "autonomy": {},
        "model": {"provider": "local", "model": "qwen2.5:14b"},  # TODO: move to config
        "voice": {
            "system_prompt": "You are a research assistant. Be thorough and cite sources.",
            "personality": "You are a thorough research assistant. Verify claims before asserting them. Cite sources when available. Prefer depth over breadth. When uncertain, say so explicitly.",
        },
    },
    "code": {
        "name": "Code",
        "description": "Software development focused room.",
        "vault_scope": {"mode": "include", "paths": ["patterns", "knowledge"]},
        "toolsets": ["vault", "system", "file", "git"],
        "autonomy": {},
        "model": {},
        "voice": {
            "system_prompt": "You are a senior software engineer. Be concise and code-first.",
            "personality": "You are a focused development assistant. Be concise. Show code first, explain second. Prefer working examples over abstract descriptions. Flag potential bugs and security issues proactively.",
        },
    },
    "writing": {
        "name": "Writing",
        "description": "Creative and technical writing.",
        "vault_scope": {"mode": "include", "paths": ["knowledge"]},
        "toolsets": ["vault", "file"],
        "autonomy": {},
        "model": {},
        "voice": {
            "system_prompt": "You are a writing assistant. Focus on clarity and style.",
            "personality": "You are a creative writing partner. Write in flowing prose — avoid bullet points unless explicitly requested. When given a prompt, produce a full draft before asking clarifying questions. Match the tone and style of the request.",
            "temperature": 0.9,
        },
    },
    "health": {
        "name": "Health",
        "description": "Health tracking and wellness.",
        "vault_scope": {"mode": "include", "paths": ["knowledge"], "tags": ["health", "wellness"]},
        "toolsets": ["vault", "system"],
        "autonomy": {},
        "model": {"provider": "local", "model": "qwen2.5:7b"},  # TODO: move to config
        "voice": {
            "system_prompt": "You are a health and wellness assistant.",
            "personality": "You are a careful health information assistant. Always cite reputable medical sources. Remind the user to consult healthcare professionals for personal medical decisions. Never diagnose or prescribe.",
        },
    },
    "finance": {
        "name": "Finance",
        "description": "Financial analysis and tracking.",
        "vault_scope": {"mode": "include", "paths": ["knowledge"], "tags": ["finance", "money"]},
        "toolsets": ["vault", "oracle", "system"],
        "autonomy": {"overrides": {"oikos_vault_ingest": "ASK_FIRST"}},
        "model": {},
        "voice": {
            "system_prompt": "You are a financial analyst. Be precise with numbers.",
            "personality": "You are a data-driven financial assistant. Present numbers, comparisons, and trends. Always disclaim that this is not financial advice. Never recommend specific investments or trades.",
        },
    },
}
