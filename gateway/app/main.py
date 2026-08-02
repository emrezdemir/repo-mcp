"""FastAPI application: the MCP endpoint and health probes."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse, Response

from .audit import AuditEvent, emit
from .auth import Authenticator, AuthError
from .cbm import CbmPool
from .config import Settings
from .llm import LlmClient
from .mcp import McpRouter, TenantSelectionError, build_session
from .metrics import AUTH_FAILURES, render
from .tenants import TenantRegistry

log = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    registry = TenantRegistry.load(settings.tenants_file)
    pool = CbmPool(settings)
    llm = LlmClient(settings)
    auth = Authenticator(settings)
    router = McpRouter(settings, registry, pool, llm)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        if settings.dev_insecure_auth:
            log.warning(
                "DEV_INSECURE_AUTH is enabled: JWT verification is skipped. "
                "Never run this in production."
            )
        _warn_on_cache_drift(settings, registry)
        await pool.start()
        try:
            yield
        finally:
            await pool.aclose()
            await llm.aclose()

    app = FastAPI(title="repo-mcp gateway", lifespan=lifespan)

    @app.get("/healthz")
    async def healthz() -> dict:
        return {"status": "ok"}

    @app.get("/readyz")
    async def readyz() -> dict:
        return {
            "status": "ok",
            "tenants": [t.name for t in registry.tenants],
            "smart_tools": llm.enabled,
        }

    @app.get("/metrics")
    async def metrics() -> Response:
        payload, content_type = render()
        return Response(content=payload, media_type=content_type)

    @app.post("/mcp")
    async def mcp_endpoint(
        request: Request,
        authorization: str | None = Header(default=None),
        x_tenant: str | None = Header(default=None),
    ):
        try:
            principal = await auth.authenticate(authorization)
        except AuthError as exc:
            emit(AuditEvent(event="auth", principal="?", outcome="denied", reason=str(exc)))
            AUTH_FAILURES.labels("authentication").inc()
            return JSONResponse({"error": str(exc)}, status_code=401)

        try:
            session = build_session(registry, principal, x_tenant)
        except TenantSelectionError as exc:
            emit(
                AuditEvent(
                    event="tenant_select",
                    principal=principal.username,
                    outcome="denied",
                    reason=str(exc),
                )
            )
            AUTH_FAILURES.labels("tenant_selection").inc()
            return JSONResponse({"error": str(exc)}, status_code=403)

        try:
            body = await request.json()
        except ValueError:
            return JSONResponse(
                {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {"code": -32700, "message": "invalid JSON"},
                },
                status_code=400,
            )

        # MCP clients may send a single message or a batch.
        if isinstance(body, list):
            responses = [
                response
                for message in body
                if (response := await router.handle(session, message)) is not None
            ]
            if not responses:
                return JSONResponse(None, status_code=202)
            return JSONResponse(responses)

        response = await router.handle(session, body)
        if response is None:
            return JSONResponse(None, status_code=202)
        return JSONResponse(response)

    return app


def _warn_on_cache_drift(settings: Settings, registry: TenantRegistry) -> None:
    """The cache directory is the isolation boundary; it must match the ACL.

    ``list_projects`` returns every project in a cache directory, so a stray
    database there leaks its name even though the gateway would refuse queries
    against it. That means the indexer placed a project where it should not
    have — worth a loud warning at startup.
    """
    for tenant in registry.tenants:
        if "*" in tenant.projects:
            continue
        cache_dir = settings.cbm_cache_root / "tenant" / tenant.name
        if not cache_dir.is_dir():
            continue
        stray = sorted(
            db.stem for db in cache_dir.glob("*.db") if not tenant.allows_project(db.stem)
        )
        if stray:
            log.warning(
                "tenant=%s has projects outside its allowlist in the cache dir: %s "
                "(list_projects will disclose these names)",
                tenant.name,
                ", ".join(stray),
            )
