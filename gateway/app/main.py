"""FastAPI application: the MCP endpoint, the admin API and health probes."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse, Response
from repo_mcp_common.bootstrap import NotBootstrapped, ensure_admin, inspect_state
from repo_mcp_common.db import Database, DatabaseUnavailable
from repo_mcp_common.env import EnvError, secrets_key

from . import firstrun, updates, webui
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
    state = {"ready": False, "needs_setup": False, "reason": "starting"}

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
            state["needs_setup"] = (
                bootstrap_state.schema_present and bootstrap_state.admin_count == 0
            )
            state["reason"] = bootstrap_state.explain()
            if state["needs_setup"]:
                # Not an error any more: a fresh install creates its first
                # administrator in the browser at /setup.
                log.info("no administrator yet — first-run setup is at /setup")
            elif not bootstrap_state.ready:
                log.error("not ready: %s", bootstrap_state.explain())
            else:
                await provider.current()
        except (DatabaseUnavailable, NotBootstrapped, EnvError) as exc:
            # Keep answering /healthz so an orchestrator reports "unhealthy"
            # with a readable reason rather than a crash loop with none.
            state["ready"] = False
            state["needs_setup"] = False
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
    def _llm_enabled(live: Settings) -> bool:
        """Whether a model backend is configured, as of right now.

        `llm.update` is idempotent and cheap; calling it here means the
        interface sees an administrator enabling the backend on the next page
        load rather than after the next tool call.
        """
        llm.update(live)
        return llm.enabled

    async def engine_ui_port(tenant) -> int | None:
        """Start this tenant's engine if it is not running, and report its port.

        Asking for the port is what starts the engine, which is the same thing
        a tool call does — the graph page is not a special case.
        """
        session = await pool.session(tenant)
        await session.ensure_started()
        return session.ui_port

    async def _create_first_admin(username: str, password: str) -> bool:
        """Create the first administrator on first-run. Raises ValueError
        (WeakPassword, AdminError are both ValueErrors) for a bad password or
        username, which the caller turns into a 400; returns False if one
        already exists."""
        created = await ensure_admin(database, username, password)
        return created is not None

    async def _refresh_bootstrap() -> None:
        """Re-read readiness so a just-created administrator makes the platform
        usable without a restart."""
        s = await inspect_state(database)
        state["ready"] = s.ready
        state["needs_setup"] = s.schema_present and s.admin_count == 0
        state["reason"] = s.explain()

    app.include_router(
        firstrun.build_router(
            lambda: bool(state["needs_setup"]),
            _create_first_admin,
            _refresh_bootstrap,
        )
    )
    app.include_router(
        webui.build_router(
            provider.current,
            lambda: bool(state["ready"]),
            engine_ui_port,
            _llm_enabled,
            needs_setup=lambda: bool(state["needs_setup"]),
        )
    )

    @app.get("/healthz")
    async def healthz() -> dict:
        return {"status": "ok"}

    @app.get("/api/version", include_in_schema=False)
    async def version_endpoint() -> JSONResponse:
        # Public: the running version, and — unless UPDATE_CHECK is off — whether
        # a newer release exists. The interface shows a banner from it.
        return JSONResponse(await updates.version_info())

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
