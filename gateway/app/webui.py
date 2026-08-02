"""The web interface, and the one endpoint it needs that MCP does not provide.

The interface deliberately has no privileged path of its own: every question it
asks about a codebase goes to `POST /mcp` as ordinary JSON-RPC, with the
caller's own token. Anything the browser can do, an MCP client can do, and it
is authorized and audited by exactly the same code — a second read API beside
the first would be a second place for the tenancy rules to be wrong.

What MCP cannot answer is "who am I here": which squad, which role, which
tools. `GET /api/session` exists for that and nothing else.

The files under `ui/` are served as they are. There is no build step and
nothing is fetched from a CDN, so the interface works in an air-gapped
installation and needs no JavaScript toolchain in this repository.
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, Header, Response
from fastapi.responses import FileResponse, JSONResponse

from .auth import Authenticator, AuthError
from .configuration import RuntimeConfig
from .mcp import TenantSelectionError, build_session
from .roles import TOOL_CAPABILITY

log = logging.getLogger(__name__)

UI_DIR = Path(__file__).parent.resolve() / "ui"

#: What the interface is made of. Everything under `ui/` is served without
#: authentication — it is the login screen and the code behind it, and none of
#: it reveals anything about a codebase. The extension list is what keeps a
#: stray file in that directory from becoming a download.
SERVED_SUFFIXES = {".html", ".css", ".js", ".svg", ".map"}


def build_router(current_config, ready) -> APIRouter:
    """The UI's own routes.

    `current_config` returns the live `RuntimeConfig`; `ready` reports whether
    the platform is configured. Both are passed in rather than imported so the
    router holds no state of its own.
    """
    router = APIRouter(tags=["ui"])

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

        allowed = session.effective_tools
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
