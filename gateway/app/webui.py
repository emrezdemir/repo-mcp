"""The web interface, and the one endpoint it needs that MCP does not provide.

The interface deliberately has no privileged path of its own: every question it
asks about a codebase goes to `POST /mcp` as ordinary JSON-RPC, with the
caller's own token. Anything the browser can do, an MCP client can do, and it
is authorized and audited by exactly the same code — a second read API beside
the first would be a second place for the tenancy rules to be wrong.

What MCP cannot answer is "who am I here": which squad, which role, which
tools. `GET /api/session` exists for that and nothing else.

What MCP also has no tool for is the 3D graph layout: the engine computes it
in C and serves it on a loopback port. `GET /api/layout` authorizes a request
the same way a tool call is authorized, then proxies to that port.

The files under `ui/` are the built interface. Its source is `gateway/webui/`;
the image build runs `npm run build` and copies the output here. Nothing is
fetched from a CDN at runtime, so an air-gapped installation works.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

import httpx
from fastapi import APIRouter, Header, Response
from fastapi.responses import FileResponse, JSONResponse

from .audit import AuditEvent, emit
from .auth import Authenticator, AuthError
from .configuration import RuntimeConfig
from .mcp import TenantSelectionError, build_session, smart_tools_for
from .roles import TOOL_CAPABILITY, Capability

log = logging.getLogger(__name__)

#: The built interface. `gateway/webui/` is the source; `npm run build` puts
#: the output here, and the image build puts it somewhere else entirely —
#: hence the override. Committing the build output would make review
#: meaningless, so it is produced rather than stored.
UI_DIR = Path(os.getenv("REPO_MCP_UI_DIR") or (Path(__file__).parent / "ui")).resolve()

#: What the interface is made of. Everything under `ui/` is served without
#: authentication — it is the login screen and the code behind it, and none of
#: it reveals anything about a codebase. The extension list is what keeps a
#: stray file in that directory from becoming a download.
SERVED_SUFFIXES = {".html", ".css", ".js", ".svg", ".map"}


def build_router(current_config, ready, engine_ui_port=None, llm_enabled=None) -> APIRouter:
    """The UI's own routes.

    `current_config` returns the live `RuntimeConfig`; `ready` reports whether
    the platform is configured; `engine_ui_port` returns the loopback port a
    tenant's engine serves its layout on, or None; `llm_enabled` takes the live
    settings and reports whether a model backend is configured — it is given
    the settings rather than asked cold, so an administrator turning the
    backend on is visible here without waiting for a request to /mcp.

    All four are passed in rather than imported, so the router holds no state
    of its own.
    """
    if engine_ui_port is None:

        async def engine_ui_port(_tenant):  # noqa: F811 — the no-engine default
            return None

    if llm_enabled is None:

        def llm_enabled(_settings) -> bool:  # noqa: F811 — the no-model default
            return False
    router = APIRouter(tags=["ui"])

    @router.get("/api/auth")
    async def auth_info() -> JSONResponse:
        """How to sign in. Answered before anyone is signed in, so it is public.

        Nothing here is a secret: an issuer URL and a public client id are
        both visible in the redirect the browser is about to make anyway. The
        interface uses this to decide between the OIDC redirect and the token
        box, rather than shipping a build-time guess about the deployment.
        """
        if not ready():
            return JSONResponse({"error": "the platform is not configured yet"}, status_code=503)

        config: RuntimeConfig = await current_config()
        settings = config.settings

        if settings.dev_insecure_auth:
            # Saying so plainly matters: this mode accepts one static token
            # and verifies nothing, and anyone looking at the sign-in screen
            # should be able to tell that is what they are looking at.
            return JSONResponse(
                {
                    "mode": "development",
                    "reason": "DEV_INSECURE_AUTH is on: tokens are not verified",
                }
            )

        if settings.oidc_issuer and settings.oidc_browser_client_id:
            return JSONResponse(
                {
                    "mode": "oidc",
                    "issuer": settings.oidc_issuer.rstrip("/"),
                    "client_id": settings.oidc_browser_client_id,
                    "audience": settings.oidc_audience,
                    "scopes": settings.oidc_browser_scopes or "openid profile",
                }
            )

        # An issuer without a browser client is the ordinary state of a
        # platform used only by MCP clients. The token box still works.
        return JSONResponse(
            {
                "mode": "token",
                "reason": (
                    "no browser client is configured; set oidc.browser_client_id "
                    "to sign in through the provider"
                ),
            }
        )

    @router.get("/api/ui-config")
    async def ui_config() -> JSONResponse:
        """What the interface needs before anyone has signed in.

        Only presentation: a language, and the platform's own name for its
        heading. Public for the same reason the sign-in screen is — it is
        read while rendering that screen.
        """
        if not ready():
            # Not an error: the interface renders in the browser's language
            # and the sign-in screen explains the rest.
            return JSONResponse({"lang": "auto"})

        config: RuntimeConfig = await current_config()
        return JSONResponse({"lang": config.settings.ui_language or "auto"})

    @router.get("/api/session")
    async def session_info(
        authorization: str | None = Header(default=None),
        x_tenant: str | None = Header(default=None),
    ) -> JSONResponse:
        """Who the caller is, and what this platform will let them do.

        The interface uses it to decide which pages to offer. Getting it wrong
        would only mean showing a button that then fails with a clear denial —
        the answer here is a convenience, not a permission.
        """
        if not ready():
            return JSONResponse({"error": "the platform is not configured yet"}, status_code=503)

        config: RuntimeConfig = await current_config()
        try:
            principal = await Authenticator(config.settings).authenticate(authorization)
        except AuthError as exc:
            return JSONResponse({"error": str(exc)}, status_code=401)

        squads = [t.name for t in config.registry.for_groups(principal.groups)]
        try:
            session = build_session(config.registry, principal, x_tenant)
        except TenantSelectionError as exc:
            # Belonging to several squads without choosing one is not an
            # error for this endpoint: the interface needs the list precisely
            # so it can offer the choice.
            return JSONResponse(
                {
                    "username": principal.username,
                    "squads": squads,
                    "squad": None,
                    "reason": str(exc),
                }
            )

        # The composite tools are the gateway's own and are not in the
        # engine's list, so they are added here the same way tools/list adds
        # them. Reporting a different set would mean offering a button the
        # platform then refuses.
        allowed = session.effective_tools | smart_tools_for(session, llm_enabled(config.settings))
        return JSONResponse(
            {
                "username": principal.username,
                "squads": squads,
                "squad": session.tenant.name,
                "role": session.role.value,
                "capabilities": sorted(c.value for c in session.capabilities),
                "tools": sorted(allowed),
                # What the interface actually branches on, so it does not have
                # to know how tools map to capabilities.
                "can": {
                    "search": "search_graph" in allowed,
                    "read_source": "get_code_snippet" in allowed,
                    "raw_query": "query_graph" in allowed,
                    "architecture": "get_architecture" in allowed,
                },
                "projects": list(session.tenant.projects),
                "tool_profile": session.tenant.tool_profile,
            }
        )

    @router.get("/api/layout")
    async def graph_layout(
        project: str,
        max_nodes: int = 5000,
        graph: str = "code",
        authorization: str | None = Header(default=None),
        x_tenant: str | None = Header(default=None),
    ) -> Response:
        """The 3D layout the graph page draws, from this squad's engine.

        This is the one thing the interface needs that MCP has no tool for:
        the engine computes the layout in C, reading the graph database
        directly, and serves it over a loopback port. Reimplementing that here
        would be slower and would drift from what the engine knows.

        It is not a second read path. The authorization is the same as a tool
        call's — the caller's token, their squad, the READ_GRAPH capability
        and the squad's project allowlist — and only then is the request
        proxied to a port that exists solely inside this container.
        """
        if not ready():
            return JSONResponse({"error": "the platform is not configured yet"}, status_code=503)

        config: RuntimeConfig = await current_config()
        try:
            principal = await Authenticator(config.settings).authenticate(authorization)
        except AuthError as exc:
            return JSONResponse({"error": str(exc)}, status_code=401)

        try:
            session = build_session(config.registry, principal, x_tenant)
        except TenantSelectionError as exc:
            return JSONResponse({"error": str(exc)}, status_code=409)

        if Capability.READ_GRAPH not in session.capabilities:
            return JSONResponse(
                {"error": f"role {session.role.value!r} cannot read the graph"}, status_code=403
            )

        if not session.tenant.allows_project(project):
            return JSONResponse(
                {
                    "error": f"no access to project {project!r} "
                    f"(allowed: {', '.join(session.tenant.projects)})"
                },
                status_code=403,
            )

        port = await engine_ui_port(session.tenant)
        if port is None:
            return JSONResponse(
                {
                    "error": "this deployment's engine does not serve the graph layout. "
                    "It needs the build of the engine that includes the interface."
                },
                status_code=503,
            )

        emit(
            AuditEvent(
                event="ui/layout",
                principal=principal.username,
                tenant=session.tenant.name,
                outcome="ok",
                extra={"project": project, "max_nodes": max_nodes},
            )
        )

        params = {"project": project, "max_nodes": str(max_nodes)}
        if graph == "missed":
            params["graph"] = "missed"

        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                upstream = await client.get(
                    f"http://127.0.0.1:{port}/api/layout",
                    params=params,
                    # The engine's server checks the Origin against its own
                    # loopback authority and refuses anything else.
                    headers={"Origin": f"http://127.0.0.1:{port}"},
                )
        except httpx.HTTPError as exc:
            log.warning("layout request to the engine failed: %s", exc)
            return JSONResponse({"error": f"the engine did not answer: {exc}"}, status_code=502)

        return Response(
            content=upstream.content,
            status_code=upstream.status_code,
            media_type=upstream.headers.get("content-type", "application/json"),
        )

    @router.get("/ui/{path:path}", include_in_schema=False)
    async def ui_files(path: str) -> Response:
        """Serve a file from `ui/`, and nothing outside it.

        The resolved path is compared against the resolved directory, so
        `../` and a symlink out are both refused — checking the string the
        client sent would only catch the first.
        """
        target = (UI_DIR / (path or "index.html")).resolve()
        if not target.is_relative_to(UI_DIR):
            return JSONResponse({"error": "not found"}, status_code=404)
        if target.suffix not in SERVED_SUFFIXES or not target.is_file():
            return JSONResponse({"error": "not found"}, status_code=404)
        return FileResponse(target)

    @router.get("/ui", include_in_schema=False)
    async def ui_root() -> Response:
        return FileResponse(UI_DIR / "index.html")

    return router


def known_tool_capabilities() -> dict[str, str]:
    """Tool → capability, for the interface's own explanation of a denial."""
    return {tool: capability.value for tool, capability in TOOL_CAPABILITY.items()}
