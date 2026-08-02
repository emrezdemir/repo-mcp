"""FastAPI application: the MCP endpoint, the admin API and health probes."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse, Response
from repo_mcp_common.bootstrap import NotBootstrapped, inspect_state
from repo_mcp_common.db import Database, DatabaseUnavailable
from repo_mcp_common.env import EnvError, secrets_key

from . import webui
from .admin_api import build_router
from .answer_cache import AnswerCache
from .audit import AuditEvent, emit
from .auth import Authenticator, AuthError
from .cbm import CbmPool
from .config import Settings
from .configuration import ConfigurationProvider
from .llm import LlmClient
from .mcp import McpRouter, TenantSelectionError, build_session
from .metrics import AUTH_FAILURES, render

log = logging.getLogger(__name__)


def create_app(settings: Settings | None = None, database: Database | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    database = database or Database()
    pool = CbmPool(settings)
    llm = LlmClient(settings)
    provider = ConfigurationProvider(database, settings)
    cache = AnswerCache(database, llm)
    # registry per request; the cache is a no-op until an administrator enables it
    router = McpRouter(settings, registry=None, pool=pool, llm=llm, cache=cache)

    #: Set once the database has a schema and an administrator. Until then the
    #: service answers health probes and nothing else, with a message naming
    #: the missing step — an unbootstrapped gateway cannot be configured, so
    #: serving requests would only produce confusing failures downstream.
    state = {"ready": False, "reason": "starting"}

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        if settings.dev_insecure_auth:
            log.warning(
                "DEV_INSECURE_AUTH is enabled: JWT verification is skipped. "
                "Never run this in production."
            )
        try:
            # Before the database, because a missing key is a deployment
            # mistake rather than a transient one: the service would start,
            # serve requests, and fail on the first credential it had to
            # decrypt — somewhere far from the cause.
            secrets_key()
            await database.wait_until_ready()
            bootstrap_state = await inspect_state(database)
            state["ready"] = bootstrap_state.ready
            state["reason"] = bootstrap_state.explain()
            if not bootstrap_state.ready:
                log.error("not ready: %s", bootstrap_state.explain())
            else:
                await provider.current()
        except (DatabaseUnavailable, NotBootstrapped, EnvError) as exc:
            # Keep answering /healthz so an orchestrator reports "unhealthy"
            # with a readable reason rather than a crash loop with none.
            state["ready"] = False
            state["reason"] = str(exc)
            log.error("%s", exc)

        await pool.start()
        try:
            yield
        finally:
            await pool.aclose()
            await llm.aclose()
            await database.aclose()

    app = FastAPI(title="repo-mcp gateway", lifespan=lifespan)
    app.include_router(build_router(database, provider))
    # The interface asks the platform the same questions an MCP client does,
    # over the same endpoint. See gateway/app/webui.py.
    app.include_router(webui.build_router(provider.current, lambda: bool(state["ready"])))

    @app.get("/healthz")
    async def healthz() -> dict:
        return {"status": "ok"}

    @app.get("/readyz")
    async def readyz() -> Response:
        if not state["ready"]:
            return JSONResponse(
                {"status": "not_ready", "reason": state["reason"]}, status_code=503
            )
        config = await provider.current()
        body = {
            "status": "ok",
            "generation": config.generation,
            "tenants": [t.name for t in config.registry.tenants],
            "smart_tools": llm.enabled,
            "database": database.env.redacted_url(),
        }
        if not config.registry.tenants:
            # Healthy but useless: every request will be denied for want of a
            # squad, and an operator should see why without reading logs.
            body["warning"] = (
                "no squads are configured; add one through the admin API or "
                "with 'repo-mcp-admin import'"
            )
        return JSONResponse(body)

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
        if not state["ready"]:
            return JSONResponse(
                {"error": f"the platform is not configured yet: {state['reason']}"},
                status_code=503,
            )

        config = await provider.current()
        # Cheap and idempotent: adopts anything an administrator changed since
        # the last request without rebuilding the client.
        llm.update(config.settings)
        auth = Authenticator(config.settings)

        try:
            principal = await auth.authenticate(authorization)
        except AuthError as exc:
            emit(AuditEvent(event="auth", principal="?", outcome="denied", reason=str(exc)))
            AUTH_FAILURES.labels("authentication").inc()
            return JSONResponse({"error": str(exc)}, status_code=401)

        try:
            session = build_session(config.registry, principal, x_tenant)
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
