"""Write operations on the configuration.

Every mutation bumps the generation counter in the same transaction, so a
reader either sees the old configuration with the old generation or the new
one with the new generation — never a half-applied edit.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from .crypto import SecretBox
from .models import (
    AdminUser,
    AuditEntry,
    ConfigGeneration,
    Connector,
    RoleAssignment,
    Secret,
    Setting,
    Tenant,
    TenantLdapGroup,
    TenantProject,
)
from .passwords import DUMMY_HASH, hash_password, verify

log = logging.getLogger(__name__)

VALID_PROFILES = {"all", "analysis", "scout"}
VALID_MODES = {"full", "moderate", "fast", "cross-repo-intelligence"}
VALID_PROVIDERS = {"github", "gitlab", "bitbucket"}
VALID_ROLES = {"admin", "lead", "developer", "qa", "devops", "viewer"}


class AdminError(ValueError):
    """An administrative operation was rejected."""


@dataclass(frozen=True)
class TenantInput:
    name: str
    ldap_groups: list[str]
    projects: list[str]
    tool_profile: str = "analysis"
    structural_only: bool = False
    denied_tools: list[str] | None = None
    litellm_key_secret: str | None = None
    enabled: bool = True


@dataclass(frozen=True)
class ConnectorInput:
    name: str
    provider: str
    tenant: str
    settings: dict
    token_secret: str | None = None
    include: list[str] | None = None
    exclude: list[str] | None = None
    mode: str = "moderate"
    persistence: bool = True
    enabled: bool = True


async def bump_generation(session: AsyncSession) -> int:
    """Advance the counter readers watch. Call inside the writing transaction."""
    row = await session.get(ConfigGeneration, 1)
    if row is None:
        row = ConfigGeneration(id=1, generation=1)
        session.add(row)
    else:
        row.generation += 1
        row.updated_at = datetime.now(UTC)
    await session.flush()
    return row.generation


async def record(
    session: AsyncSession, actor: str, action: str, target: str | None = None, **detail
) -> None:
    session.add(AuditEntry(actor=actor, action=action, target=target, detail=detail or None))


# ── administrators ───────────────────────────────────────────────────


async def admin_count(session: AsyncSession) -> int:
    rows = (await session.execute(select(AdminUser).where(AdminUser.is_active.is_(True)))).scalars()
    return len(list(rows))


async def create_admin(
    session: AsyncSession, username: str, password: str, *, actor: str = "system"
) -> AdminUser:
    username = username.strip().lower()
    if not username:
        raise AdminError("username must not be empty")
    existing = (
        await session.execute(select(AdminUser).where(AdminUser.username == username))
    ).scalar_one_or_none()
    if existing is not None:
        raise AdminError(f"an administrator named {username!r} already exists")

    user = AdminUser(username=username, password_hash=hash_password(password))
    session.add(user)
    await record(session, actor, "admin.create", username)
    await session.flush()
    return user


async def authenticate_admin(
    session: AsyncSession, username: str, password: str
) -> AdminUser | None:
    user = (
        await session.execute(
            select(AdminUser).where(AdminUser.username == username.strip().lower())
        )
    ).scalar_one_or_none()
    # Verify even when the user does not exist, so a missing account and a
    # wrong password take the same time.
    ok = verify(user.password_hash if user else DUMMY_HASH, password)
    if user is None or not user.is_active or not ok:
        return None
    user.last_login_at = datetime.now(UTC)
    return user


async def set_admin_password(
    session: AsyncSession, username: str, password: str, *, actor: str
) -> None:
    user = (
        await session.execute(select(AdminUser).where(AdminUser.username == username.lower()))
    ).scalar_one_or_none()
    if user is None:
        raise AdminError(f"no administrator named {username!r}")
    user.password_hash = hash_password(password)
    user.must_change_password = False
    await record(session, actor, "admin.password_change", username)


# ── secrets ──────────────────────────────────────────────────────────


async def put_secret(
    session: AsyncSession,
    name: str,
    value: str,
    *,
    actor: str,
    description: str | None = None,
) -> None:
    box = SecretBox()
    row = (await session.execute(select(Secret).where(Secret.name == name))).scalar_one_or_none()
    if row is None:
        session.add(Secret(name=name, ciphertext=box.encrypt(value), description=description))
        action = "secret.create"
    else:
        row.ciphertext = box.encrypt(value)
        if description is not None:
            row.description = description
        action = "secret.update"
    # The value never reaches the audit detail.
    await record(session, actor, action, name)
    await bump_generation(session)


async def delete_secret(session: AsyncSession, name: str, *, actor: str) -> None:
    await session.execute(delete(Secret).where(Secret.name == name))
    await record(session, actor, "secret.delete", name)
    await bump_generation(session)


# ── tenants and roles ────────────────────────────────────────────────


async def upsert_tenant(session: AsyncSession, data: TenantInput, *, actor: str) -> Tenant:
    if data.tool_profile not in VALID_PROFILES:
        raise AdminError(
            f"unknown tool_profile {data.tool_profile!r} "
            f"(expected one of {', '.join(sorted(VALID_PROFILES))})"
        )
    if not data.ldap_groups:
        raise AdminError("a tenant needs at least one LDAP group")
    if not data.projects:
        raise AdminError("a tenant needs at least one project pattern")

    tenant = (
        await session.execute(select(Tenant).where(Tenant.name == data.name))
    ).scalar_one_or_none()

    # One group mapping to two squads would make the isolation boundary
    # ambiguous, so reject it here rather than letting the loader choose.
    clashes = (
        await session.execute(
            select(TenantLdapGroup).where(TenantLdapGroup.group_name.in_(data.ldap_groups))
        )
    ).scalars().all()
    for clash in clashes:
        if tenant is None or clash.tenant_id != tenant.id:
            raise AdminError(
                f"LDAP group {clash.group_name!r} is already mapped to another squad"
            )

    if tenant is None:
        tenant = Tenant(name=data.name)
        session.add(tenant)
        action = "tenant.create"
    else:
        action = "tenant.update"

    tenant.tool_profile = data.tool_profile
    tenant.structural_only = data.structural_only
    tenant.denied_tools = list(data.denied_tools or [])
    tenant.litellm_key_secret = data.litellm_key_secret
    tenant.enabled = data.enabled
    await session.flush()

    await session.execute(delete(TenantLdapGroup).where(TenantLdapGroup.tenant_id == tenant.id))
    await session.execute(delete(TenantProject).where(TenantProject.tenant_id == tenant.id))
    for group in dict.fromkeys(data.ldap_groups):
        session.add(TenantLdapGroup(tenant_id=tenant.id, group_name=group))
    for pattern in dict.fromkeys(data.projects):
        session.add(TenantProject(tenant_id=tenant.id, pattern=pattern))

    await record(session, actor, action, data.name, tool_profile=data.tool_profile)
    await bump_generation(session)
    return tenant


async def delete_tenant(session: AsyncSession, name: str, *, actor: str) -> None:
    tenant = (
        await session.execute(select(Tenant).where(Tenant.name == name))
    ).scalar_one_or_none()
    if tenant is None:
        raise AdminError(f"no tenant named {name!r}")
    await session.delete(tenant)
    await record(session, actor, "tenant.delete", name)
    await bump_generation(session)


async def set_role_groups(
    session: AsyncSession, role: str, groups: list[str], *, actor: str
) -> None:
    if role not in VALID_ROLES:
        raise AdminError(
            f"unknown role {role!r} (expected one of {', '.join(sorted(VALID_ROLES))})"
        )
    await session.execute(delete(RoleAssignment).where(RoleAssignment.role == role))
    for group in dict.fromkeys(groups):
        session.add(RoleAssignment(role=role, group_name=group))
    await record(session, actor, "role.set", role, groups=list(groups))
    await bump_generation(session)


# ── connectors ───────────────────────────────────────────────────────


async def upsert_connector(session: AsyncSession, data: ConnectorInput, *, actor: str) -> Connector:
    if data.provider not in VALID_PROVIDERS:
        raise AdminError(
            f"unknown provider {data.provider!r} "
            f"(expected one of {', '.join(sorted(VALID_PROVIDERS))})"
        )
    if data.mode not in VALID_MODES:
        raise AdminError(
            f"unknown mode {data.mode!r} (expected one of {', '.join(sorted(VALID_MODES))})"
        )

    tenant = (
        await session.execute(select(Tenant).where(Tenant.name == data.tenant))
    ).scalar_one_or_none()
    if tenant is None:
        raise AdminError(f"no tenant named {data.tenant!r}; create the squad first")

    connector = (
        await session.execute(select(Connector).where(Connector.name == data.name))
    ).scalar_one_or_none()
    if connector is None:
        connector = Connector(name=data.name)
        session.add(connector)
        action = "connector.create"
    else:
        action = "connector.update"

    connector.provider = data.provider
    connector.tenant_id = tenant.id
    connector.settings = dict(data.settings)
    connector.token_secret = data.token_secret
    connector.include = list(data.include or ["*"])
    connector.exclude = list(data.exclude or [])
    connector.mode = data.mode
    connector.persistence = data.persistence
    connector.enabled = data.enabled

    await record(session, actor, action, data.name, provider=data.provider, tenant=data.tenant)
    await bump_generation(session)
    await session.flush()
    return connector


async def delete_connector(session: AsyncSession, name: str, *, actor: str) -> None:
    connector = (
        await session.execute(select(Connector).where(Connector.name == name))
    ).scalar_one_or_none()
    if connector is None:
        raise AdminError(f"no connector named {name!r}")
    await session.delete(connector)
    await record(session, actor, "connector.delete", name)
    await bump_generation(session)


# ── settings ─────────────────────────────────────────────────────────


async def set_setting(session: AsyncSession, key: str, value, *, actor: str) -> None:
    row = await session.get(Setting, key)
    if row is None:
        session.add(Setting(key=key, value=value))
    else:
        row.value = value
    # Values here are not secrets — those are referenced by name — so the new
    # value is safe to record.
    await record(session, actor, "setting.set", key, value=value)
    await bump_generation(session)
