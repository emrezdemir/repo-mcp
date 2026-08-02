"""Database schema.

Everything an administrator changes during normal operation lives here.
Infrastructure that must be known *before* the database can be read —
`DATABASE_URL`, `SECRETS_KEY`, the bind port, the engine paths — stays in the
environment, because reading it from the database would be circular.

See docs/adr/0006-configuration-in-the-database.md.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, server_default=func.now()
    )


class AdminUser(TimestampMixin, Base):
    """A break-glass local administrator.

    Deliberately separate from LDAP identity: before anyone has configured the
    identity provider, nobody can log in through it. Someone has to be able to
    perform that first configuration. See ADR-0007.
    """

    __tablename__ = "admin_users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    #: Argon2id. Never a reversible encoding.
    password_hash: Mapped[str] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    #: Forces a change on next login; set when an administrator resets someone.
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Secret(TimestampMixin, Base):
    """An encrypted credential, referenced by name.

    Ciphertext only. The key lives in `SECRETS_KEY` in the environment, so a
    database dump is not by itself a credential disclosure.
    """

    __tablename__ = "secrets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    ciphertext: Mapped[str] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)


class Tenant(TimestampMixin, Base):
    """A squad. The isolation unit for graph stores and authorization."""

    __tablename__ = "tenants"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    #: all | analysis | scout — mirrors the engine's own profile names.
    tool_profile: Mapped[str] = mapped_column(String(16), default="analysis")
    #: Withhold tools that return source text (the org-wide shared layer).
    structural_only: Mapped[bool] = mapped_column(Boolean, default=False)
    denied_tools: Mapped[list] = mapped_column(JSON, default=list)
    #: Name of a Secret holding this squad's LiteLLM virtual key.
    litellm_key_secret: Mapped[str | None] = mapped_column(String(128), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)

    ldap_groups: Mapped[list[TenantLdapGroup]] = relationship(
        back_populates="tenant", cascade="all, delete-orphan", lazy="selectin"
    )
    projects: Mapped[list[TenantProject]] = relationship(
        back_populates="tenant", cascade="all, delete-orphan", lazy="selectin"
    )


class TenantLdapGroup(Base):
    """One directory group granting membership of a squad.

    Unique across all tenants: mapping one group to two squads would make the
    effective isolation boundary ambiguous, so the database refuses it rather
    than letting the loader pick.
    """

    __tablename__ = "tenant_ldap_groups"
    __table_args__ = (UniqueConstraint("group_name", name="uq_tenant_ldap_group"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    group_name: Mapped[str] = mapped_column(String(128), index=True)

    tenant: Mapped[Tenant] = relationship(back_populates="ldap_groups")


class TenantProject(Base):
    """A glob pattern of project names this squad may query."""

    __tablename__ = "tenant_projects"
    __table_args__ = (UniqueConstraint("tenant_id", "pattern", name="uq_tenant_project"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    pattern: Mapped[str] = mapped_column(String(256))

    tenant: Mapped[Tenant] = relationship(back_populates="projects")


class RoleAssignment(Base):
    """A directory group granting a role.

    Roles and squads are orthogonal — role decides what you may do, squad
    decides to which data (ADR-0003) — so this table does not reference
    tenants.
    """

    __tablename__ = "role_assignments"
    __table_args__ = (UniqueConstraint("role", "group_name", name="uq_role_group"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    role: Mapped[str] = mapped_column(String(32), index=True)
    group_name: Mapped[str] = mapped_column(String(128), index=True)


class Connector(TimestampMixin, Base):
    """A repository source: a GitHub org, GitLab group or Bitbucket workspace."""

    __tablename__ = "connectors"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    #: github | gitlab | bitbucket
    provider: Mapped[str] = mapped_column(String(32))
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    #: Provider-specific fields: org, group, workspace, project_key, base_url.
    settings: Mapped[dict] = mapped_column(JSON, default=dict)
    #: Name of the Secret holding the access token.
    token_secret: Mapped[str | None] = mapped_column(String(128), nullable=True)
    include: Mapped[list] = mapped_column(JSON, default=lambda: ["*"])
    exclude: Mapped[list] = mapped_column(JSON, default=list)
    #: full | moderate | fast | cross-repo-intelligence
    mode: Mapped[str] = mapped_column(String(32), default="moderate")
    persistence: Mapped[bool] = mapped_column(Boolean, default=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)

    tenant: Mapped[Tenant] = relationship(lazy="selectin")


class Setting(TimestampMixin, Base):
    """A single administrator-editable value, stored as JSON.

    Flat key-value rather than a column per setting: adding a tunable should
    not require a migration, and the admin API validates against a schema in
    `settings_schema.py` instead.
    """

    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value: Mapped[dict] = mapped_column(JSON)


class ConfigGeneration(Base):
    """A counter bumped on every configuration write.

    Services cache configuration and re-read only when this changes, so an
    administrative edit reaches every replica within one poll interval without
    a restart, and without every request hitting the database.
    """

    __tablename__ = "config_generation"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    generation: Mapped[int] = mapped_column(Integer, default=1)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, server_default=func.now()
    )


class AuditEntry(Base):
    """Administrative changes.

    Tool calls are audited to stdout as structured logs; this table is only
    for configuration changes, because "who added this tenant, and when" is a
    question the file-based configuration could not answer at all.
    """

    __tablename__ = "admin_audit"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now(), index=True
    )
    actor: Mapped[str] = mapped_column(String(128))
    action: Mapped[str] = mapped_column(String(64))
    target: Mapped[str | None] = mapped_column(String(256), nullable=True)
    detail: Mapped[dict | None] = mapped_column(JSON, nullable=True)
