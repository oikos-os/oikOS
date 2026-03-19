"""Pydantic v2 models for oikOS Rooms."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field, field_validator

_ROOM_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")
_AUTONOMY_LEVELS = {"SAFE", "ASK_FIRST", "PROHIBITED"}


class RoomVaultScope(BaseModel):
    """Which vault content a Room can access."""

    mode: Literal["all", "include", "exclude"] = "all"
    paths: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)

    @field_validator("paths")
    @classmethod
    def _validate_paths(cls, v: list[str]) -> list[str]:
        for p in v:
            if ".." in p or "\x00" in p:
                raise ValueError(f"Path '{p}' contains illegal characters")
            if re.match(r"^[A-Za-z]:", p) or p.startswith("/"):
                raise ValueError(f"Path '{p}' must be relative, not absolute")
        return v


class RoomAutonomy(BaseModel):
    """Per-tool autonomy overrides for a Room."""

    overrides: dict[str, str] = Field(default_factory=dict)

    @field_validator("overrides")
    @classmethod
    def _validate_levels(cls, v: dict[str, str]) -> dict[str, str]:
        for tool, level in v.items():
            if level not in _AUTONOMY_LEVELS:
                raise ValueError(f"Invalid autonomy level '{level}' for tool '{tool}'. Must be one of {_AUTONOMY_LEVELS}")
        return v


class RoomModelConfig(BaseModel):
    """Inference model configuration for a Room."""

    provider: str | None = None
    model: str | None = None
    fallback_provider: str | None = None
    fallback_model: str | None = None


class RoomVoice(BaseModel):
    """Voice and personality configuration for a Room."""

    system_prompt: str | None = None
    personality: str | None = None
    temperature: float | None = None


class RoomLimits(BaseModel):
    """Per-Room operational limits."""

    max_tokens_per_query: int | None = None
    max_tool_calls_per_session: int | None = None
    monthly_cloud_budget_cents: int | None = None
    session_isolation: bool = True

    @field_validator("max_tokens_per_query", "max_tool_calls_per_session", "monthly_cloud_budget_cents")
    @classmethod
    def _validate_non_negative(cls, v: int | None) -> int | None:
        if v is not None and v < 0:
            raise ValueError("Limit values must be non-negative")
        return v


class RoomConfig(BaseModel):
    """Top-level configuration for an oikOS Room."""

    id: str
    name: str
    description: str | None = None
    vault_scope: RoomVaultScope = Field(default_factory=RoomVaultScope)
    toolsets: list[str] | None = None
    autonomy: RoomAutonomy = Field(default_factory=RoomAutonomy)
    model: RoomModelConfig = Field(default_factory=RoomModelConfig)
    voice: RoomVoice = Field(default_factory=RoomVoice)
    limits: RoomLimits = Field(default_factory=RoomLimits)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator("id")
    @classmethod
    def _validate_id(cls, v: str) -> str:
        if not _ROOM_ID_RE.match(v):
            raise ValueError(f"Room id '{v}' must match ^[a-z0-9][a-z0-9_-]{{0,31}}$")
        return v
