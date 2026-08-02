"""Tests for the configuration database.

They run against SQLite through aiosqlite, so no database server is needed and
they stay in the unit layer. The schema comes from the same Alembic migration
PostgreSQL gets, so a schema mistake fails here rather than at deploy time.
"""

from __future__ import annotations

import pytest
from cryptography.fernet import Fernet

from repo_mcp_common import bootstrap as boot
from repo_mcp_common.admin import (
    AdminError,
    ConnectorInput,
    TenantInput,
    authenticate_admin,
    create_admin,
    delete_tenant,
    put_secret,
    set_role_groups,
    set_setting,
    upsert_connector,
    upsert_tenant,
)
from repo_mcp_common.crypto import DecryptionError, SecretBox
from repo_mcp_common.db import Database
from repo_mcp_common.env import DatabaseEnv
from repo_mcp_common.passwords import WeakPassword, hash_password, verify
from repo_mcp_common.store import ConfigStore


@pytest.fixture
def key(monkeypatch) -> str:
    value = Fernet.generate_key().decode()
    monkeypatch.setenv("SECRETS_KEY", value)
    return value


@pytest.fixture
async def database(tmp_path, key) -> Database:
    env = DatabaseEnv(
        url=f"sqlite+aiosqlite:///{tmp_path / 'config.db'}",
        pool_size=1,
        pool_max_overflow=0,
        config_poll_seconds=0,
        connect_retry_seconds=5,
    )
    db = Database(env)
    await db.wait_until_ready()
    await boot.upgrade_schema(db)
    yield db
    await db.aclose()


async def seed_tenant(db: Database, name: str = "payments", **overrides) -> None:
    data = {
        "name": name,
        "ldap_groups": [f"squad-{name}"],
        "projects": [f"acme-{name}-*"],
        "tool_profile": "analysis",
    }
    data.update(overrides)
    async with db.session() as session:
        await upsert_tenant(session, TenantInput(**data), actor="test")


# ── bootstrap ────────────────────────────────────────────────────────


async def test_a_fresh_database_is_not_ready(tmp_path, key):
    env = DatabaseEnv(
        url=f"sqlite+aiosqlite:///{tmp_path / 'empty.db'}",
        pool_size=1, pool_max_overflow=0, config_poll_seconds=0, connect_retry_seconds=5,
    )
    db = Database(env)
    await db.wait_until_ready()
    state = await boot.inspect_state(db)
    assert state.ready is False
    assert "no schema" in state.explain()
    await db.aclose()


async def test_schema_without_an_administrator_is_not_ready(database):
    state = await boot.inspect_state(database)
    assert state.schema_present is True
    assert state.admin_count == 0
    assert state.ready is False
    assert "no administrator" in state.explain()


async def test_bootstrap_creates_the_first_administrator(database):
    created = await boot.ensure_admin(database, "admin", "correct-horse-battery")
    assert created is not None
    assert created.generated is False
    assert (await boot.inspect_state(database)).ready is True


async def test_bootstrap_generates_a_password_when_none_is_given(database):
    created = await boot.ensure_admin(database, "admin")
    assert created is not None and created.generated is True
    assert len(created.password) >= 20


async def test_bootstrap_is_idempotent_and_never_resets_a_password(database):
    first = await boot.ensure_admin(database, "admin", "correct-horse-battery")
    second = await boot.ensure_admin(database, "admin", "something-else-here")
    assert second is None, "a second bootstrap must not touch the existing account"
    async with database.session() as session:
        assert await authenticate_admin(session, "admin", first.password) is not None


async def test_upgrade_schema_can_be_run_twice(database):
    await boot.upgrade_schema(database)
    assert (await boot.inspect_state(database)).schema_present is True


# ── passwords ────────────────────────────────────────────────────────


async def test_authentication_accepts_the_right_password_only(database):
    async with database.session() as session:
        await create_admin(session, "admin", "correct-horse-battery", actor="test")
    async with database.session() as session:
        assert await authenticate_admin(session, "admin", "correct-horse-battery") is not None
        assert await authenticate_admin(session, "admin", "wrong-horse-battery") is None
        assert await authenticate_admin(session, "nobody", "correct-horse-battery") is None


def test_passwords_are_hashed_not_stored():
    stored = hash_password("correct-horse-battery")
    assert "correct-horse-battery" not in stored
    assert stored.startswith("$argon2id$")
    assert verify(stored, "correct-horse-battery")


@pytest.mark.parametrize("bad", ["short", "aaaaaaaaaaaaaaaa", ""])
def test_weak_passwords_are_rejected(bad):
    with pytest.raises(WeakPassword):
        hash_password(bad)


# ── secrets ──────────────────────────────────────────────────────────


async def test_secrets_are_encrypted_at_rest(database, key):
    async with database.session() as session:
        await put_secret(session, "github.token", "ghp_verysecretvalue", actor="test")

    from sqlalchemy import select

    from repo_mcp_common.models import Secret

    async with database.read() as session:
        row = (await session.execute(select(Secret))).scalar_one()
    assert "ghp_verysecretvalue" not in row.ciphertext

    snapshot = await ConfigStore(database, poll_seconds=0).snapshot()
    assert snapshot.secrets["github.token"] == "ghp_verysecretvalue"


def test_a_wrong_key_reports_the_key_not_corruption():
    box = SecretBox(Fernet.generate_key().decode())
    ciphertext = box.encrypt("value")
    other = SecretBox(Fernet.generate_key().decode())
    with pytest.raises(DecryptionError, match="SECRETS_KEY"):
        other.decrypt(ciphertext)


# ── tenants and roles ────────────────────────────────────────────────


async def test_a_tenant_round_trips_into_the_document_shape(database):
    await seed_tenant(database, "payments", structural_only=False)
    snapshot = await ConfigStore(database, poll_seconds=0).snapshot()
    entry = snapshot.tenants_document["tenants"]["payments"]
    assert entry["tool_profile"] == "analysis"
    assert entry["ldap_groups"] == ["squad-payments"]
    assert entry["projects"] == ["acme-payments-*"]


async def test_one_ldap_group_cannot_map_to_two_squads(database):
    await seed_tenant(database, "payments", ldap_groups=["shared"])
    with pytest.raises(AdminError, match="already mapped"):
        await seed_tenant(database, "checkout", ldap_groups=["shared"])


async def test_updating_a_tenant_keeps_its_own_groups(database):
    await seed_tenant(database, "payments", ldap_groups=["squad-payments"])
    await seed_tenant(database, "payments", ldap_groups=["squad-payments", "chapter-test"])
    snapshot = await ConfigStore(database, poll_seconds=0).snapshot()
    assert snapshot.tenants_document["tenants"]["payments"]["ldap_groups"] == [
        "chapter-test",
        "squad-payments",
    ]


@pytest.mark.parametrize("profile", ["root", "", "ALL"])
async def test_an_unknown_tool_profile_is_rejected(database, profile):
    with pytest.raises(AdminError, match="unknown tool_profile"):
        await seed_tenant(database, "payments", tool_profile=profile)


async def test_an_unknown_role_is_rejected(database):
    async with database.session() as session:
        with pytest.raises(AdminError, match="unknown role"):
            await set_role_groups(session, "superuser", ["g"], actor="test")


async def test_a_disabled_tenant_disappears_from_the_document(database):
    await seed_tenant(database, "payments")
    await seed_tenant(database, "payments", enabled=False)
    snapshot = await ConfigStore(database, poll_seconds=0).snapshot()
    assert "payments" not in snapshot.tenants_document["tenants"]


async def test_deleting_a_tenant_removes_its_groups(database):
    await seed_tenant(database, "payments", ldap_groups=["shared"])
    async with database.session() as session:
        await delete_tenant(session, "payments", actor="test")
    # The group is free again, which proves the cascade ran.
    await seed_tenant(database, "checkout", ldap_groups=["shared"])


# ── connectors ───────────────────────────────────────────────────────


async def test_a_connector_round_trips_with_its_provider_settings(database):
    await seed_tenant(database, "payments")
    async with database.session() as session:
        await put_secret(session, "gh.token", "ghp_token", actor="test")
        await upsert_connector(
            session,
            ConnectorInput(
                name="acme-github",
                provider="github",
                tenant="payments",
                settings={"org": "acme", "base_url": "https://api.github.com"},
                token_secret="gh.token",
                include=["payments-*"],
                mode="fast",
            ),
            actor="test",
        )

    snapshot = await ConfigStore(database, poll_seconds=0).snapshot()
    entry = snapshot.scan_document["connectors"][0]
    assert entry["type"] == "github"
    assert entry["tenant"] == "payments"
    assert entry["org"] == "acme"
    assert entry["token_secret"] == "gh.token"
    assert snapshot.secrets["gh.token"] == "ghp_token"


async def test_a_connector_needs_an_existing_tenant(database):
    async with database.session() as session:
        with pytest.raises(AdminError, match="no tenant named"):
            await upsert_connector(
                session,
                ConnectorInput(name="c", provider="github", tenant="ghost", settings={}),
                actor="test",
            )


@pytest.mark.parametrize(
    "field,value,message",
    [("provider", "svn", "unknown provider"), ("mode", "turbo", "unknown mode")],
)
async def test_invalid_connector_fields_are_rejected(database, field, value, message):
    await seed_tenant(database, "payments")
    data = {"name": "c", "provider": "github", "tenant": "payments", "settings": {}, field: value}
    async with database.session() as session:
        with pytest.raises(AdminError, match=message):
            await upsert_connector(session, ConnectorInput(**data), actor="test")


# ── caching and the generation counter ───────────────────────────────


async def test_the_generation_advances_on_every_write(database):
    store = ConfigStore(database, poll_seconds=0)
    before = (await store.snapshot()).generation
    await seed_tenant(database, "payments")
    after = (await store.snapshot()).generation
    assert after > before


async def test_a_cached_snapshot_is_reused_until_the_generation_moves(database):
    await seed_tenant(database, "payments")
    store = ConfigStore(database, poll_seconds=60)
    first = await store.snapshot()
    await seed_tenant(database, "checkout")
    # Still inside the poll interval, so the cached snapshot is served.
    assert (await store.snapshot()) is first
    await store.invalidate()
    assert "checkout" in (await store.snapshot()).tenants_document["tenants"]


async def test_settings_fall_back_to_defaults_then_take_overrides(database):
    store = ConfigStore(database, poll_seconds=0)
    assert (await store.snapshot()).setting("litellm.model") == "gpt-4o-mini"
    async with database.session() as session:
        await set_setting(session, "litellm.model", "ollama/qwen2.5-coder:14b", actor="test")
    assert (await store.snapshot()).setting("litellm.model") == "ollama/qwen2.5-coder:14b"


# ── import ───────────────────────────────────────────────────────────


async def test_importing_the_yaml_documents_seeds_the_database(database, monkeypatch):
    monkeypatch.setenv("GH_TOKEN", "ghp_fromenvironment")
    counts = await boot.import_documents(
        database,
        {
            "roles": {"developer": ["squad-payments"]},
            "tenants": {
                "payments": {
                    "ldap_groups": ["squad-payments"],
                    "projects": ["acme-*"],
                    "tool_profile": "analysis",
                }
            },
        },
        {
            "connectors": [
                {
                    "name": "acme-github",
                    "type": "github",
                    "org": "acme",
                    "tenant": "payments",
                    "token_env": "GH_TOKEN",
                    "mode": "moderate",
                }
            ]
        },
    )
    assert counts == {"tenants": 1, "roles": 1, "connectors": 1, "secrets": 1}

    snapshot = await ConfigStore(database, poll_seconds=0).snapshot()
    assert snapshot.tenants_document["roles"] == {"developer": ["squad-payments"]}
    # The token value moved out of the environment and into encrypted storage.
    assert snapshot.secrets["connector.acme-github.token"] == "ghp_fromenvironment"


async def test_importing_twice_updates_rather_than_duplicates(database):
    document = {
        "tenants": {
            "payments": {"ldap_groups": ["squad-payments"], "projects": ["a-*"]}
        }
    }
    await boot.import_documents(database, document, None)
    await boot.import_documents(database, document, None)
    snapshot = await ConfigStore(database, poll_seconds=0).snapshot()
    assert list(snapshot.tenants_document["tenants"]) == ["payments"]


# ── the documents drive the real registries ──────────────────────────


async def test_the_document_builds_the_gateway_registry_unchanged(database):
    """The point of the document shape: authorization code did not change."""
    pytest.importorskip("app.tenants")
    from app.tenants import TenantRegistry

    await seed_tenant(database, "payments", tool_profile="scout", structural_only=True)
    async with database.session() as session:
        await set_role_groups(session, "developer", ["squad-payments"], actor="test")

    snapshot = await ConfigStore(database, poll_seconds=0).snapshot()
    registry = TenantRegistry.from_dict(snapshot.tenants_document)

    tenant = registry.by_name("payments")
    assert tenant.cbm_profile_flag() == ["--tool-profile=scout"]
    assert "get_code_snippet" not in tenant.allowed_tools
    assert registry.role_for(frozenset({"squad-payments"})).value == "developer"
