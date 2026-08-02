"""First-boot setup: schema, the first administrator, and optional seeding.

Both services refuse to serve traffic until the database has a schema and at
least one active administrator. That is deliberate: an unbootstrapped gateway
with no administrator has no way to be configured, so answering requests would
only produce confusing failures further downstream.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import yaml
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect

from .admin import (
    ConnectorInput,
    TenantInput,
    admin_count,
    create_admin,
    put_secret,
    set_role_groups,
    upsert_connector,
    upsert_tenant,
)
from .db import Database
from .models import AdminUser
from .passwords import generate as generate_password

log = logging.getLogger(__name__)

MIGRATIONS_PATH = Path(__file__).parent / "migrations"


class NotBootstrapped(RuntimeError):
    """The database has no schema, or no administrator."""


@dataclass(frozen=True)
class BootstrapState:
    schema_present: bool
    admin_count: int

    @property
    def ready(self) -> bool:
        return self.schema_present and self.admin_count > 0

    def explain(self) -> str:
        if not self.schema_present:
            return (
                "the database has no schema. Run:  repo-mcp-admin init-db\n"
                "(the bundled Compose stack does this automatically on first start)"
            )
        if self.admin_count == 0:
            return (
                "the database has no administrator. Run:  repo-mcp-admin create-admin\n"
                "Until then there is no way to configure the platform."
            )
        return "ready"


async def inspect_state(database: Database) -> BootstrapState:
    engine = database.connect()

    def _tables(connection) -> list[str]:
        return inspect(connection).get_table_names()

    async with engine.connect() as connection:
        tables = await connection.run_sync(_tables)

    if "admin_users" not in tables:
        return BootstrapState(schema_present=False, admin_count=0)

    async with database.read() as session:
        return BootstrapState(schema_present=True, admin_count=await admin_count(session))


async def require_ready(database: Database) -> None:
    state = await inspect_state(database)
    if not state.ready:
        raise NotBootstrapped(state.explain())


# ── schema ───────────────────────────────────────────────────────────


def alembic_config(url: str) -> Config:
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_PATH))
    # Alembic runs synchronously; strip the async driver from the URL.
    config.set_main_option("sqlalchemy.url", url.replace("+asyncpg", "").replace("+aiosqlite", ""))
    return config


async def upgrade_schema(database: Database) -> None:
    """Apply migrations up to head. Safe to run on every start."""
    engine = database.connect()

    def _upgrade(connection) -> None:
        config = alembic_config(database.env.url)
        config.attributes["connection"] = connection
        command.upgrade(config, "head")

    async with engine.begin() as connection:
        await connection.run_sync(_upgrade)
    log.info("database schema is at head")


# ── first administrator ──────────────────────────────────────────────


@dataclass(frozen=True)
class CreatedAdmin:
    username: str
    password: str
    generated: bool


async def ensure_admin(
    database: Database, username: str, password: str | None = None
) -> CreatedAdmin | None:
    """Create the first administrator if there is not one already.

    Returns None when an administrator already exists, so re-running the
    bootstrap is harmless and never silently resets a password.
    """
    async with database.session() as session:
        if await admin_count(session) > 0:
            return None
        generated = password is None
        secret = password or generate_password()
        await create_admin(session, username, secret, actor="bootstrap")
        return CreatedAdmin(username=username, password=secret, generated=generated)


async def has_admin(database: Database) -> bool:
    async with database.read() as session:
        return await admin_count(session) > 0


# ── seeding from the legacy YAML ─────────────────────────────────────


async def import_documents(
    database: Database,
    tenants_document: dict | None = None,
    scan_document: dict | None = None,
    *,
    actor: str = "import",
    secrets_from_env: bool = True,
) -> dict[str, int]:
    """Seed the database from the YAML shapes configuration used to have.

    Idempotent: re-importing updates rather than duplicating, so it can be run
    against a partly configured database.
    """
    counts = {"tenants": 0, "roles": 0, "connectors": 0, "secrets": 0}

    async with database.session() as session:
        for role, groups in (tenants_document or {}).get("roles", {}).items():
            await set_role_groups(session, role, list(groups), actor=actor)
            counts["roles"] += 1

        for name, entry in (tenants_document or {}).get("tenants", {}).items():
            await upsert_tenant(
                session,
                TenantInput(
                    name=str(name),
                    ldap_groups=[str(g) for g in entry.get("ldap_groups", [])],
                    projects=[str(p) for p in entry.get("projects", [])],
                    tool_profile=str(entry.get("tool_profile", "analysis")),
                    structural_only=bool(entry.get("structural_only", False)),
                    denied_tools=[str(t) for t in entry.get("denied_tools", [])],
                ),
                actor=actor,
            )
            counts["tenants"] += 1

    async with database.session() as session:
        reserved = {
            "name", "type", "tenant", "token_env", "token_secret",
            "include", "exclude", "mode", "persistence", "schedule_cron",
        }
        for entry in (scan_document or {}).get("connectors", []):
            token_secret = entry.get("token_secret")
            token_env = entry.get("token_env")

            # The YAML referenced a token by environment variable name. If that
            # variable is set, move the value into the database so the operator
            # does not have to re-enter it; otherwise record the reference and
            # let them fill it in.
            if token_env and secrets_from_env:
                import os

                value = os.getenv(str(token_env), "")
                secret_name = token_secret or f"connector.{entry['name']}.token"
                if value:
                    await put_secret(
                        session,
                        secret_name,
                        value,
                        actor=actor,
                        description=f"imported from ${token_env}",
                    )
                    counts["secrets"] += 1
                token_secret = secret_name

            await upsert_connector(
                session,
                ConnectorInput(
                    name=str(entry["name"]),
                    provider=str(entry["type"]).lower(),
                    tenant=str(entry["tenant"]),
                    settings={k: v for k, v in entry.items() if k not in reserved},
                    token_secret=token_secret,
                    include=[str(p) for p in entry.get("include", ["*"])],
                    exclude=[str(p) for p in entry.get("exclude", [])],
                    mode=str(entry.get("mode", "moderate")),
                    persistence=bool(entry.get("persistence", True)),
                ),
                actor=actor,
            )
            counts["connectors"] += 1

    return counts


def read_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


__all__ = [
    "AdminUser",
    "BootstrapState",
    "CreatedAdmin",
    "NotBootstrapped",
    "ensure_admin",
    "has_admin",
    "import_documents",
    "inspect_state",
    "read_yaml",
    "require_ready",
    "upgrade_schema",
]
