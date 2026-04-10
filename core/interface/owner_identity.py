"""Owner identity loader — parameterizes PII defense for a given deployment.

The PII defense modules (content_classifier, pii, adversarial, complexity,
confidence, interface/config) used to hardcode the operator's identity
literally. This module replaces that with a config-driven loader.

The config file lives at ``config/owner_identity.toml`` (gitignored). A
documented placeholder ships as ``config/owner_identity.example.toml``.
When the config is absent the loader returns a no-op ``OwnerIdentity`` —
all lists empty, all flags off — and logs a one-time warning. Consumers
degrade gracefully: generic PII heuristics still run, but owner-specific
whitelists and NEVER_LEAVE patterns are disabled.

Tests override the path via the ``OIKOS_OWNER_IDENTITY_PATH`` environment
variable (see ``tests/fixtures/test_owner_identity.toml``).
"""

from __future__ import annotations

import logging
import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)

_CONFIG_ENV_VAR = "OIKOS_OWNER_IDENTITY_PATH"
_DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent.parent.parent / "config" / "owner_identity.toml"


@dataclass(frozen=True)
class OwnerIdentity:
    """Immutable owner-identity profile loaded from ``owner_identity.toml``.

    All fields default to empty — an unconfigured instance is a valid
    no-op profile that disables owner-specific PII defense.
    """

    full_name: str = ""
    first_name: str = ""
    nicknames: tuple[str, ...] = ()
    usernames: tuple[str, ...] = ()
    emails: tuple[str, ...] = ()
    deprecated_systems: tuple[str, ...] = ()

    vault_root: str = ""
    file_agent_paths: dict[str, str] = field(default_factory=dict)

    complexity_domains: dict[str, frozenset[str]] = field(default_factory=dict)
    vault_entities: tuple[str, ...] = ()

    gauntlet_identity_name: str = ""
    gauntlet_identity_keywords: tuple[str, ...] = ()
    gauntlet_age_probe_query: str = ""
    gauntlet_age_probe_forbidden: tuple[str, ...] = ()
    gauntlet_deprecated_probe_query: str = ""

    @property
    def is_configured(self) -> bool:
        """True when at least one owner-identity field is populated."""
        return bool(
            self.full_name
            or self.first_name
            or self.nicknames
            or self.usernames
            or self.deprecated_systems
            or self.file_agent_paths
            or self.complexity_domains
            or self.vault_entities
            or self.gauntlet_identity_name
        )

    def persona_whitelist(self) -> frozenset[str]:
        """Lowercase set of names that should not be flagged as random PII.

        Includes first name, nicknames, and deprecated-system names.
        Consumers merge this with their own built-in project whitelist.
        """
        items: list[str] = []
        if self.first_name:
            items.append(self.first_name.lower())
        items.extend(n.lower() for n in self.nicknames)
        items.extend(d.lower() for d in self.deprecated_systems)
        return frozenset(items)

    def never_leave_tokens(self) -> tuple[str, ...]:
        """Exact tokens that must route to NEVER_LEAVE tier unconditionally."""
        return tuple(self.usernames) + tuple(self.emails) + tuple(self.deprecated_systems)


_cached: OwnerIdentity | None = None
_warned_missing = False


def _resolve_path() -> Path:
    override = os.environ.get(_CONFIG_ENV_VAR)
    if override:
        return Path(override)
    return _DEFAULT_CONFIG_PATH


def _coerce_str_tuple(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(str(v) for v in value if isinstance(v, str))


def _coerce_domain_map(value: object) -> dict[str, frozenset[str]]:
    if not isinstance(value, dict):
        return {}
    result: dict[str, frozenset[str]] = {}
    for domain, body in value.items():
        if not isinstance(domain, str):
            continue
        keywords = body.get("keywords") if isinstance(body, dict) else None
        result[domain] = frozenset(
            str(k).lower() for k in keywords if isinstance(k, str)
        ) if isinstance(keywords, list) else frozenset()
    return result


def _coerce_path_map(value: object) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {
        str(k): str(v).upper()
        for k, v in value.items()
        if isinstance(k, str) and isinstance(v, str) and str(v).upper() in {"READ", "READ_WRITE"}
    }


def _parse(data: dict) -> OwnerIdentity:
    owner = data.get("owner", {}) if isinstance(data.get("owner"), dict) else {}
    paths = data.get("paths", {}) if isinstance(data.get("paths"), dict) else {}
    complexity = data.get("complexity", {}) if isinstance(data.get("complexity"), dict) else {}
    confidence = data.get("confidence", {}) if isinstance(data.get("confidence"), dict) else {}
    gauntlet = data.get("gauntlet", {}) if isinstance(data.get("gauntlet"), dict) else {}

    return OwnerIdentity(
        full_name=str(owner.get("full_name", "")),
        first_name=str(owner.get("first_name", "")),
        nicknames=_coerce_str_tuple(owner.get("nicknames")),
        usernames=_coerce_str_tuple(owner.get("usernames")),
        emails=_coerce_str_tuple(owner.get("emails")),
        deprecated_systems=_coerce_str_tuple(owner.get("deprecated_systems")),
        vault_root=str(paths.get("vault_root", "")),
        file_agent_paths=_coerce_path_map(paths.get("file_agent")),
        complexity_domains=_coerce_domain_map(complexity.get("domains")),
        vault_entities=_coerce_str_tuple(confidence.get("vault_entities")),
        gauntlet_identity_name=str(gauntlet.get("identity_name", "")),
        gauntlet_identity_keywords=_coerce_str_tuple(gauntlet.get("identity_keywords")),
        gauntlet_age_probe_query=str(gauntlet.get("age_probe_query", "")),
        gauntlet_age_probe_forbidden=_coerce_str_tuple(gauntlet.get("age_probe_forbidden")),
        gauntlet_deprecated_probe_query=str(gauntlet.get("deprecated_system_probe_query", "")),
    )


def load_owner_identity() -> OwnerIdentity:
    """Return the cached owner identity, loading from disk on first call.

    Returns an empty no-op ``OwnerIdentity`` when the config file is
    missing or malformed, and logs a warning exactly once per process.
    """
    global _cached, _warned_missing
    if _cached is not None:
        return _cached

    path = _resolve_path()
    if not path.exists():
        if not _warned_missing:
            log.warning(
                "owner_identity config not found at %s — PII defense running "
                "with empty-owner profile. Copy config/owner_identity.example.toml "
                "to %s and populate it to enable owner-specific detection.",
                path, path.name,
            )
            _warned_missing = True
        _cached = OwnerIdentity()
        return _cached

    try:
        with path.open("rb") as f:
            data = tomllib.load(f)
        _cached = _parse(data)
        log.info("owner_identity loaded from %s (configured=%s)", path, _cached.is_configured)
    except (tomllib.TOMLDecodeError, OSError) as e:
        log.warning("owner_identity load failed (%s) — falling back to empty profile", e)
        _cached = OwnerIdentity()

    return _cached


def reset_cache() -> None:
    """Clear the loader cache. Used by tests that mutate the config path."""
    global _cached, _warned_missing
    _cached = None
    _warned_missing = False
