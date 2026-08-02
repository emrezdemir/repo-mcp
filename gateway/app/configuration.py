"""Runtime configuration, sourced from the database.

The gateway used to read `tenants.yaml` once at startup. It now reads the same
document shape out of PostgreSQL through the shared store, so an administrator
can change a squad without a restart and every replica sees the same thing.

`Settings` still exists and still comes from the environment — it holds the
handful of values that must be known *before* the database can be read. See
docs/adr/0006-configuration-in-the-database.md.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace

from repo_mcp_common.db import Database
from repo_mcp_common.store import ConfigSnapshot, ConfigStore

from .config import Settings
from .tenants import TenantRegistry

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class RuntimeConfig:
    """One consistent view of everything the request path needs."""

    generation: int
    registry: TenantRegistry
    settings: Settings
    #: Secret name → plaintext, already decrypted.
    secrets: dict[str, str]

    def litellm_key_for(self, secret_name: str | None) -> str | None:
        if not secret_name:
            return None
        return self.secrets.get(secret_name)


class ConfigurationProvider:
    """Builds a `RuntimeConfig` from the database, cached by generation.

    The registry is rebuilt only when the generation moves, so the request
    path costs a dictionary lookup rather than a query.
    """

    def __init__(self, database: Database, base: Settings) -> None:
        self._store = ConfigStore(database)
        self._base = base
        self._current: RuntimeConfig | None = None

    async def current(self) -> RuntimeConfig:
        snapshot = await self._store.snapshot()
        if self._current is not None and self._current.generation == snapshot.generation:
            return self._current
        self._current = self._build(snapshot)
        log.info(
            "configuration applied: generation %d, %d tenant(s)",
            snapshot.generation,
            len(self._current.registry.tenants),
        )
        return self._current

    async def invalidate(self) -> None:
        """Force the next read to hit the database. Used after an admin write."""
        await self._store.invalidate()
        self._current = None

    def _build(self, snapshot: ConfigSnapshot) -> RuntimeConfig:
        registry = TenantRegistry.from_dict(snapshot.tenants_document)

        # Administrator-editable settings override the environment defaults.
        # The environment keeps only what bootstrapping needs.
        settings = replace(
            self._base,
            oidc_issuer=str(snapshot.setting("oidc.issuer") or self._base.oidc_issuer),
            oidc_audience=str(snapshot.setting("oidc.audience") or self._base.oidc_audience),
            oidc_groups_claim=str(
                snapshot.setting("oidc.groups_claim") or self._base.oidc_groups_claim
            ),
            oidc_browser_client_id=str(
                snapshot.setting("oidc.browser_client_id") or self._base.oidc_browser_client_id
            ),
            oidc_browser_scopes=str(
                snapshot.setting("oidc.browser_scopes") or self._base.oidc_browser_scopes
            ),
            ui_language=str(snapshot.setting("ui.language") or self._base.ui_language),
            litellm_base_url=str(snapshot.setting("litellm.base_url") or ""),
            litellm_api_key=snapshot.secrets.get(
                str(snapshot.setting("litellm.api_key_secret") or ""), ""
            ),
            litellm_model=str(snapshot.setting("litellm.model")),
            litellm_timeout_s=float(snapshot.setting("litellm.timeout_seconds")),
            smart_tools_enabled=bool(snapshot.setting("smart_tools.enabled")),
            cbm_idle_timeout_s=float(snapshot.setting("engine.idle_timeout_seconds")),
            cbm_call_timeout_s=float(snapshot.setting("engine.call_timeout_seconds")),
            answer_cache_enabled=bool(snapshot.setting("answer_cache.enabled")),
            answer_cache_embedding_model=str(snapshot.setting("answer_cache.embedding_model")),
            answer_cache_threshold=float(snapshot.setting("answer_cache.similarity_threshold")),
            answer_cache_ttl_s=float(snapshot.setting("answer_cache.ttl_seconds")),
            headroom_enabled=bool(snapshot.setting("headroom.enabled")),
            headroom_base_url=str(snapshot.setting("headroom.base_url") or ""),
            headroom_fallback=bool(snapshot.setting("headroom.fallback_to_litellm")),
        )

        return RuntimeConfig(
            generation=snapshot.generation,
            registry=registry,
            settings=settings,
            secrets=dict(snapshot.secrets),
        )
