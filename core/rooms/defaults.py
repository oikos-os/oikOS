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
        voice={},
        limits={"session_isolation": False},
    )


TEMPLATES: dict[str, dict] = {
    "researcher": {
        "name": "Research",
        "description": "Deep research with browser and vault access.",
        "vault_scope": {"mode": "all"},
        "toolsets": ["vault", "browser", "research", "system"],
        "autonomy": {},
        "model": {"provider": "local", "model": "qwen2.5:14b"},
        "voice": {"system_prompt": "You are a research assistant. Be thorough and cite sources."},
    },
    "code": {
        "name": "Code",
        "description": "Software development focused room.",
        "vault_scope": {"mode": "include", "paths": ["patterns", "knowledge"]},
        "toolsets": ["vault", "system", "file", "git"],
        "autonomy": {},
        "model": {},
        "voice": {"system_prompt": "You are a senior software engineer. Be concise and code-first."},
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
            "temperature": 0.9,
        },
    },
    "health": {
        "name": "Health",
        "description": "Health tracking and wellness.",
        "vault_scope": {"mode": "include", "paths": ["knowledge"], "tags": ["health", "wellness"]},
        "toolsets": ["vault", "system"],
        "autonomy": {},
        "model": {"provider": "local", "model": "qwen2.5:7b"},
        "voice": {"system_prompt": "You are a health and wellness assistant."},
    },
    "finance": {
        "name": "Finance",
        "description": "Financial analysis and tracking.",
        "vault_scope": {"mode": "include", "paths": ["knowledge"], "tags": ["finance", "money"]},
        "toolsets": ["vault", "oracle", "system"],
        "autonomy": {"overrides": {"oikos_vault_ingest": "ASK_FIRST"}},
        "model": {},
        "voice": {"system_prompt": "You are a financial analyst. Be precise with numbers."},
    },
}
