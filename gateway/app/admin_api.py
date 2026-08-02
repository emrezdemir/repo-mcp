"""The administrative API.

Local administrator accounts reach this and nothing else — they cannot call
MCP tools, query a graph or read source. That scope is what makes a
password-based credential acceptable in a system whose authorization model is
otherwise entirely directory-driven. See
docs/adr/0007-break-glass-administrator.md.
"""

from __future__ import annotations

import logging
import secrets as stdlib_secrets
import time
from dataclasses import dataclass

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from repo_mcp_common.admin import (
    AdminError,
    ConnectorInput,
    TenantInput,
    authenticate_admin,
    delete_connector,
    delete_secret,
    delete_tenant,
    put_secret,
    set_admin_password,
    set_role_groups,
    set_setting,
    upsert_connector,
    upsert_tenant,
)
from repo_mcp_common.db import Database
from repo_mcp_common.models import AdminUser, AuditEntry, Connector, Secret, Setting, Tenant
from repo_mcp_common.passwords import WeakPassword
from repo_mcp_common.store import DEFAULT_SETTINGS
from sqlalchemy import select

from .audit import AuditEvent, emit
from .configuration import ConfigurationProvider

log = logging.getLogger(__name__)

#: Administrative sessions are short-lived by design: this is a break-glass
#: path, not a place to stay logged in.
SESSION_TTL_SECONDS = 8 * 3600


@dataclass
class Session:
    username: str
    expires_at: float


class SessionStore:
    """In-memory bearer tokens for the administrative API.

    Deliberately not persisted: a restart ending every administrative session
    is the safe direction, and it keeps one more table out of the schema.
    With several replicas an administrator may need to log in again after
    being routed elsewhere, which is acceptable for how rarely this is used.
    """

    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}

    def issue(self, username: str) -> tuple[str, int]:
        token = stdlib_secrets.token_urlsafe(32)
        self._sessions[token] = Session(username, time.time() + SESSION_TTL_SECONDS)
        self._reap()
        return token, SESSION_TTL_SECONDS

    def resolve(self, token: str) -> str | None:
        session = self._sessions.get(token)
        if session is None:
            return None
        if session.expires_at < time.time():
            self._sessions.pop(token, None)
            return None
        return session.username

    def revoke(self, token: str) -> None:
        self._sessions.pop(token, None)

    def _reap(self) -> None:
        now = time.time()
        for token in [t for t, s in self._sessions.items() if s.expires_at < now]:
            self._sessions.pop(token, None)


# ── request models ───────────────────────────────────────────────────


class LoginRequest(BaseModel):
    username: str
    password: str


class PasswordRequest(BaseModel):
    password: str = Field(min_length=12)


class TenantRequest(BaseModel):
    ldap_groups: list[str] = Field(min_length=1)
    projects: list[str] = Field(min_length=1)
    tool_profile: str = "analysis"
    structural_only: bool = False
    denied_tools: list[str] = Field(default_factory=list)
    litellm_key_secret: str | None = None
    enabled: bool = True


class ConnectorRequest(BaseModel):
    provider: str
    tenant: str
    settings: dict = Field(default_factory=dict)
    token_secret: str | None = None
    include: list[str] = Field(default_factory=lambda: ["*"])
    exclude: list[str] = Field(default_factory=list)
    mode: str = "moderate"
    persistence: bool = True
    enabled: bool = True


class SecretRequest(BaseModel):
    value: str = Field(min_length=1)
    description: str | None = None


class SettingRequest(BaseModel):
    value: object


class RoleRequest(BaseModel):
    groups: list[str]


def build_router(database: Database, provider: ConfigurationProvider) -> APIRouter:
    router = APIRouter(prefix="/admin", tags=["admin"])
    sessions = SessionStore()

    async def current_admin(authorization: str | None = Header(default=None)) -> str:
        scheme, _, token = (authorization or "").partition(" ")
        username = sessions.resolve(token.strip()) if scheme.lower() == "bearer" else None
        if username is None:
            raise HTTPException(status_code=401, detail="administrative session required")
        return username

    Actor = Depends(current_admin)

    def audit(actor: str, action: str, target: str | None = None, outcome: str = "ok") -> None:
        emit(
            AuditEvent(
                event=f"admin/{action}",
                principal=actor,
                outcome=outcome,
                extra={"target": target} if target else {},
            )
        )

    # ── session ──────────────────────────────────────────────────────

    @router.post("/login")
    async def login(request: LoginRequest) -> dict:
        async with database.session() as session:
            user = await authenticate_admin(session, request.username, request.password)
        if user is None:
            emit(
                AuditEvent(
                    event="admin/login",
                    principal=request.username,
                    outcome="denied",
                    reason="invalid credentials",
                )
            )
            raise HTTPException(status_code=401, detail="invalid credentials")

        token, ttl = sessions.issue(user.username)
        audit(user.username, "login")
        return {
            "token": token,
            "expires_in": ttl,
            "username": user.username,
            "must_change_password": user.must_change_password,
        }

    @router.post("/logout")
    async def logout(authorization: str | None = Header(default=None)) -> dict:
        _, _, token = (authorization or "").partition(" ")
        sessions.revoke(token.strip())
        return {"status": "ok"}

    @router.post("/password")
    async def change_password(request: PasswordRequest, actor: str = Actor) -> dict:
        try:
            async with database.session() as session:
                await set_admin_password(session, actor, request.password, actor=actor)
        except (AdminError, WeakPassword) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        audit(actor, "password_change")
        return {"status": "ok"}

    # ── state ────────────────────────────────────────────────────────

    @router.get("/config")
    async def read_config(actor: str = Actor) -> dict:
        config = await provider.current()
        async with database.read() as session:
            tenants = (await session.execute(select(Tenant))).scalars().all()
            connectors = (await session.execute(select(Connector))).scalars().all()
            settings = (await session.execute(select(Setting))).scalars().all()
            secret_rows = (await session.execute(select(Secret))).scalars().all()
            admins = (await session.execute(select(AdminUser))).scalars().all()

        return {
            "generation": config.generation,
            "tenants": [
                {
                    "name": t.name,
                    "tool_profile": t.tool_profile,
                    "structural_only": t.structural_only,
                    "enabled": t.enabled,
                    "ldap_groups": sorted(g.group_name for g in t.ldap_groups),
                    "projects": sorted(p.pattern for p in t.projects),
                }
                for t in tenants
            ],
            "connectors": [
                {
                    "name": c.name,
                    "provider": c.provider,
                    "tenant": c.tenant.name,
                    "mode": c.mode,
                    "enabled": c.enabled,
                    "settings": c.settings,
                    "token_secret": c.token_secret,
                }
                for c in connectors
            ],
            "settings": {**DEFAULT_SETTINGS, **{s.key: s.value for s in settings}},
            # Names and descriptions only. Values never leave the platform.
            "secrets": [{"name": s.name, "description": s.description} for s in secret_rows],
            "admins": [
                {"username": a.username, "is_active": a.is_active, "last_login_at": a.last_login_at}
                for a in admins
            ],
        }

    @router.get("/audit")
    async def read_audit(limit: int = 100, actor: str = Actor) -> dict:
        async with database.read() as session:
            rows = (
                await session.execute(
                    select(AuditEntry).order_by(AuditEntry.at.desc()).limit(min(limit, 500))
                )
            ).scalars().all()
        return {
            "entries": [
                {
                    "at": row.at,
                    "actor": row.actor,
                    "action": row.action,
                    "target": row.target,
                    "detail": row.detail,
                }
                for row in rows
            ]
        }

    # ── tenants and roles ────────────────────────────────────────────

    @router.put("/tenants/{name}")
    async def put_tenant(name: str, request: TenantRequest, actor: str = Actor) -> dict:
        try:
            async with database.session() as session:
                await upsert_tenant(
                    session,
                    TenantInput(
                        name=name,
                        ldap_groups=request.ldap_groups,
                        projects=request.projects,
                        tool_profile=request.tool_profile,
                        structural_only=request.structural_only,
                        denied_tools=request.denied_tools,
                        litellm_key_secret=request.litellm_key_secret,
                        enabled=request.enabled,
                    ),
                    actor=actor,
                )
        except AdminError as exc:
            audit(actor, "tenant.put", name, outcome="rejected")
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        await provider.invalidate()
        audit(actor, "tenant.put", name)
        return {"status": "ok", "tenant": name}

    @router.delete("/tenants/{name}")
    async def remove_tenant(name: str, actor: str = Actor) -> dict:
        try:
            async with database.session() as session:
                await delete_tenant(session, name, actor=actor)
        except AdminError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        await provider.invalidate()
        audit(actor, "tenant.delete", name)
        return {"status": "ok"}

    @router.put("/roles/{role}")
    async def put_role(role: str, request: RoleRequest, actor: str = Actor) -> dict:
        try:
            async with database.session() as session:
                await set_role_groups(session, role, request.groups, actor=actor)
        except AdminError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        await provider.invalidate()
        audit(actor, "role.put", role)
        return {"status": "ok", "role": role}

    # ── connectors ───────────────────────────────────────────────────

    @router.put("/connectors/{name}")
    async def put_connector(name: str, request: ConnectorRequest, actor: str = Actor) -> dict:
        try:
            async with database.session() as session:
                await upsert_connector(
                    session,
                    ConnectorInput(
                        name=name,
                        provider=request.provider,
                        tenant=request.tenant,
                        settings=request.settings,
                        token_secret=request.token_secret,
                        include=request.include,
                        exclude=request.exclude,
                        mode=request.mode,
                        persistence=request.persistence,
                        enabled=request.enabled,
                    ),
                    actor=actor,
                )
        except AdminError as exc:
            audit(actor, "connector.put", name, outcome="rejected")
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        await provider.invalidate()
        audit(actor, "connector.put", name)
        return {"status": "ok", "connector": name}

    @router.delete("/connectors/{name}")
    async def remove_connector(name: str, actor: str = Actor) -> dict:
        try:
            async with database.session() as session:
                await delete_connector(session, name, actor=actor)
        except AdminError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        await provider.invalidate()
        audit(actor, "connector.delete", name)
        return {"status": "ok"}

    # ── secrets and settings ─────────────────────────────────────────

    @router.put("/secrets/{name}")
    async def put_secret_value(name: str, request: SecretRequest, actor: str = Actor) -> dict:
        async with database.session() as session:
            await put_secret(
                session, name, request.value, actor=actor, description=request.description
            )
        await provider.invalidate()
        # The value is never logged, here or in the database audit table.
        audit(actor, "secret.put", name)
        return {"status": "ok", "secret": name}

    @router.delete("/secrets/{name}")
    async def remove_secret(name: str, actor: str = Actor) -> dict:
        async with database.session() as session:
            await delete_secret(session, name, actor=actor)
        await provider.invalidate()
        audit(actor, "secret.delete", name)
        return {"status": "ok"}

    @router.put("/settings/{key}")
    async def put_setting(key: str, request: SettingRequest, actor: str = Actor) -> dict:
        if key not in DEFAULT_SETTINGS:
            raise HTTPException(
                status_code=400,
                detail=f"unknown setting {key!r} (known: {', '.join(sorted(DEFAULT_SETTINGS))})",
            )
        async with database.session() as session:
            await set_setting(session, key, request.value, actor=actor)
        await provider.invalidate()
        audit(actor, "setting.put", key)
        return {"status": "ok", "setting": key}

    return router
