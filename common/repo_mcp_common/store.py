"""Reading configuration out of the database.

The store produces exactly the document shapes the YAML files used to hold, so
`TenantRegistry.from_dict` and `ScanConfig.from_dict` are unchanged and every
test written against them still applies. Moving the source of truth should not
have rippled through the authorization code, and it did not.

Reads are cached and refreshed only when the generation counter changes, so a
configuration edit reaches every replica within one poll interval without
putting the database on the request path.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass

from sqlalchemy import select

from .crypto import SecretBox
from .db import Database
from .models import ConfigGeneration, Connector, RoleAssignment, Secret, Setting, Tenant

log = logging.getLogger(__name__)

#: Settings an administrator may change, with the defaults used when unset.
#: Adding a tunable is a row, not a migration.
DEFAULT_SETTINGS: dict[str, object] = {
    "oidc.issuer": "",
    "oidc.audience": "repo-mcp",
    "oidc.groups_claim": "groups",
    "litellm.base_url": "",
    "litellm.model": "gpt-4o-mini",
    "litellm.timeout_seconds": 90,
    "litellm.api_key_secret": "",
    "smart_tools.enabled": True,
    "engine.idle_timeout_seconds": 900,
    "engine.call_timeout_seconds": 120,
    "indexer.concurrency": 2,
    "indexer.rescan_interval_seconds": 86400,
    "indexer.git_timeout_seconds": 600,
    "indexer.index_timeout_seconds": 3600,
    # Answer cache — docs/adr/0009-answer-cache.md. Off by default: it stores
    # synthesised knowledge of a squad's source, which is a decision an
    # administrator should make rather than inherit.
    "answer_cache.enabled": False,
    "answer_cache.embedding_model": "",
    # High on purpose. A miss costs tokens and seconds; a false hit is fluent,
    # plausible, about a different question, and very hard to notice.
    "answer_cache.similarity_threshold": 0.95,
    "answer_cache.ttl_seconds": 604800,
    # Headroom, the prompt compression proxy — docs/adr/0010-headroom-plugin.md.
    # Off by default: it changes what the model is told, which is an
    # administrator's decision to make knowingly.
    "headroom.enabled": False,
    "headroom.base_url": "",
    # On an unreachable proxy, answer through LiteLLM directly rather than
    # failing. A compression layer must not be able to take down answering.
    "headroom.fallback_to_litellm": True,
}


@dataclass(frozen=True)
class ConfigSnapshot:
    """Everything both services need, as of one generation."""

    generation: int
    tenants_document: dict
    scan_document: dict
    settings: dict
    #: Secret name → plaintext. Resolved once here so callers never touch
    #: ciphertext or the key.
    secrets: dict[str, str]

    def setting(self, key: str, default: object = None) -> object:
        if key in self.settings:
            return self.settings[key]
        if default is not None:
            return default
        return DEFAULT_SETTINGS.get(key)


class ConfigStore:
    """Loads and caches the configuration snapshot."""

    def __init__(self, database: Database, poll_seconds: float | None = None) -> None:
        self._db = database
        self._poll = poll_seconds if poll_seconds is not None else database.env.config_poll_seconds
        self._box: SecretBox | None = None
        self._snapshot: ConfigSnapshot | None = None
        self._checked_at = 0.0
        self._lock = asyncio.Lock()

    def _secret_box(self) -> SecretBox:
        if self._box is None:
            self._box = SecretBox()
        return self._box

    # ── public API ───────────────────────────────────────────────────

    async def snapshot(self) -> ConfigSnapshot:
        """The current configuration, reloading only when it has changed."""
        now = time.monotonic()
        if self._snapshot is not None and now - self._checked_at < self._poll:
            return self._snapshot

        async with self._lock:
            # Another caller may have refreshed while we waited.
            if self._snapshot is not None and time.monotonic() - self._checked_at < self._poll:
                return self._snapshot

            generation = await self._current_generation()
            self._checked_at = time.monotonic()
            if self._snapshot is not None and self._snapshot.generation == generation:
                return self._snapshot

            self._snapshot = await self._load(generation)
            log.info("configuration loaded, generation %d", generation)
            return self._snapshot

    async def invalidate(self) -> None:
        """Drop the cache so the next read hits the database."""
        async with self._lock:
            self._snapshot = None
            self._checked_at = 0.0

    # ── loading ──────────────────────────────────────────────────────

    async def _current_generation(self) -> int:
        async with self._db.read() as session:
            row = await session.get(ConfigGeneration, 1)
            return row.generation if row else 0

    async def _load(self, generation: int) -> ConfigSnapshot:
        async with self._db.read() as session:
            tenants = (await session.execute(select(Tenant).order_by(Tenant.name))).scalars().all()
            roles = (await session.execute(select(RoleAssignment))).scalars().all()
            connectors = (
                await session.execute(select(Connector).order_by(Connector.name))
            ).scalars().all()
            settings_rows = (await session.execute(select(Setting))).scalars().all()
            secret_rows = (await session.execute(select(Secret))).scalars().all()

        secrets: dict[str, str] = {}
        if secret_rows:
            box = self._secret_box()
            for row in secret_rows:
                try:
                    secrets[row.name] = box.decrypt(row.ciphertext)
                except Exception as exc:  # noqa: BLE001 - one bad secret must
                    # not make the whole configuration unloadable; the feature
                    # that needs it will fail with its own message.
                    log.error("cannot decrypt secret %r: %s", row.name, exc)

        settings = dict(DEFAULT_SETTINGS)
        settings.update({row.key: row.value for row in settings_rows})

        return ConfigSnapshot(
            generation=generation,
            tenants_document=_tenants_document(tenants, roles),
            scan_document=_scan_document(connectors),
            settings=settings,
            secrets=secrets,
        )


def _tenants_document(tenants: list[Tenant], roles: list[RoleAssignment]) -> dict:
    """Build the document `TenantRegistry.from_dict` expects."""
    role_map: dict[str, list[str]] = {}
    for assignment in roles:
        role_map.setdefault(assignment.role, []).append(assignment.group_name)

    tenant_map: dict[str, dict] = {}
    for tenant in tenants:
        if not tenant.enabled:
            continue
        entry: dict = {
            "ldap_groups": sorted(g.group_name for g in tenant.ldap_groups),
            "tool_profile": tenant.tool_profile,
            "projects": sorted(p.pattern for p in tenant.projects),
        }
        if tenant.structural_only:
            entry["structural_only"] = True
        if tenant.denied_tools:
            entry["denied_tools"] = list(tenant.denied_tools)
        if tenant.litellm_key_secret:
            entry["litellm_key_secret"] = tenant.litellm_key_secret
        tenant_map[tenant.name] = entry

    document: dict = {"tenants": tenant_map}
    if role_map:
        document["roles"] = {role: sorted(groups) for role, groups in role_map.items()}
    return document


def _scan_document(connectors: list[Connector]) -> dict:
    """Build the document `ScanConfig.from_dict` expects."""
    entries = []
    for connector in connectors:
        if not connector.enabled:
            continue
        entry: dict = {
            "name": connector.name,
            "type": connector.provider,
            "tenant": connector.tenant.name,
            "include": list(connector.include or ["*"]),
            "exclude": list(connector.exclude or []),
            "mode": connector.mode,
            "persistence": connector.persistence,
        }
        if connector.token_secret:
            entry["token_secret"] = connector.token_secret
        entry.update(connector.settings or {})
        entries.append(entry)
    return {"connectors": entries}
