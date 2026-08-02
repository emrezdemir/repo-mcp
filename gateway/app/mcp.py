"""The MCP surface exposed to agents (JSON-RPC over HTTP).

Engine tools are proxied through a filter, with LLM-backed composite tools added
on top. Authorization is applied independently in three places:

1. here — role capabilities, tenant tool profile and project allowlist;
2. in the engine process — via ``--tool-profile``;
3. on the filesystem — per-tenant ``CBM_CACHE_DIR`` and ``CBM_ALLOWED_ROOT``.

A mistake in any one layer does not open the others.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from .answer_cache import AnswerCache
from .audit import AuditEvent, Timer, emit
from .auth import Principal
from .cbm import CbmError, CbmPool
from .config import Settings
from .llm import LlmClient, LlmError
from .metrics import REQUESTS, TOOL_CALLS, TOOL_DURATION
from .roles import TOOL_CAPABILITY, Capability, Role, capabilities_for
from .smart_tools import (
    HANDLERS,
    SMART_TOOL_DEFINITIONS,
    SMART_TOOL_NAMES,
    SMART_TOOL_REQUIREMENTS,
)
from .tenants import Tenant, TenantRegistry

log = logging.getLogger(__name__)

PROTOCOL_VERSION = "2025-06-18"

#: Tools that accept a project argument. When present, it is checked against
#: the tenant's allowlist.
PROJECT_ARG_TOOLS = frozenset(
    {
        "search_graph",
        "query_graph",
        "trace_path",
        "get_code_snippet",
        "get_graph_schema",
        "get_architecture",
        "search_code",
        "index_status",
        "check_index_coverage",
        "detect_changes",
        "delete_project",
        "manage_adr",
        "ingest_traces",
        "explain_change_impact",
        "ask_codebase",
    }
)


#: Methods that get their own metric label; everything else is "other", so a
#: client probing random method names cannot inflate label cardinality.
_KNOWN_METHODS = frozenset({"initialize", "tools/list", "tools/call", "ping"})


class AccessDenied(Exception):
    """Authorization failure, surfaced as a JSON-RPC error."""


class TenantSelectionError(Exception):
    """The caller's effective squad could not be determined."""


@dataclass(frozen=True)
class Session:
    """Who is calling, as which role, scoped to which squad."""

    principal: Principal
    tenant: Tenant
    role: Role

    @property
    def capabilities(self) -> frozenset[Capability]:
        return capabilities_for(self.role)

    @property
    def effective_tools(self) -> frozenset[str]:
        """Tenant profile intersected with role capabilities.

        The two filters are independent: an admin working inside a squad whose
        profile is ``scout`` still only sees the scout tools.
        """
        caps = self.capabilities
        return frozenset(
            tool
            for tool in self.tenant.allowed_tools
            if TOOL_CAPABILITY.get(tool) in caps
        )


def select_tenant(
    registry: TenantRegistry, principal: Principal, requested: str | None
) -> Tenant:
    candidates = registry.for_groups(principal.groups)
    if not candidates:
        raise TenantSelectionError(
            "none of your LDAP groups map to a squad; contact the platform team"
        )
    if requested:
        match = next((t for t in candidates if t.name == requested), None)
        if match is None:
            raise TenantSelectionError(
                f"no access to squad {requested!r} "
                f"(available: {', '.join(t.name for t in candidates)})"
            )
        return match
    if len(candidates) > 1:
        # Picking one silently would read from, or write to, the wrong store.
        raise TenantSelectionError(
            "you belong to several squads; select one with the X-Tenant header: "
            + ", ".join(t.name for t in candidates)
        )
    return candidates[0]


def build_session(
    registry: TenantRegistry, principal: Principal, requested_tenant: str | None
) -> Session:
    return Session(
        principal=principal,
        tenant=select_tenant(registry, principal, requested_tenant),
        role=registry.role_for(principal.groups),
    )


class McpRouter:
    def __init__(
        self,
        settings: Settings,
        registry: TenantRegistry | None,
        pool: CbmPool,
        llm: LlmClient,
        cache: AnswerCache | None = None,
    ) -> None:
        #: Paths and process settings, from the environment. Tenancy arrives
        #: per request inside the Session, because an administrator can change
        #: it while the service runs; `registry` is kept only so tests can
        #: build a router without a database.
        self._settings = settings
        self._registry = registry
        self._pool = pool
        self._llm = llm
        #: Optional: tests build a router without a database.
        self._cache = cache

    async def handle(self, session: Session, message: dict) -> dict | None:
        method = message.get("method")
        message_id = message.get("id")

        if message_id is None:  # notification: no response
            return None

        label = method if method in _KNOWN_METHODS else "other"
        try:
            if method == "initialize":
                result = self._initialize()
            elif method == "tools/list":
                result = {"tools": await self._tools_list(session)}
            elif method == "tools/call":
                result = await self._tools_call(session, message.get("params") or {})
            elif method == "ping":
                result = {}
            else:
                REQUESTS.labels(label, "unknown_method").inc()
                return _error(message_id, -32601, f"unknown method: {method}")
        except AccessDenied as exc:
            REQUESTS.labels(label, "denied").inc()
            return _error(message_id, -32001, str(exc))
        except (CbmError, LlmError) as exc:
            REQUESTS.labels(label, "error").inc()
            return _error(message_id, -32000, str(exc))

        REQUESTS.labels(label, "ok").inc()
        return {"jsonrpc": "2.0", "id": message_id, "result": result}

    # ── methods ──────────────────────────────────────────────────────

    def _initialize(self) -> dict:
        return {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "repo-mcp", "version": "0.1.0"},
        }

    async def _tools_list(self, session: Session) -> list[dict]:
        allowed = session.effective_tools
        cbm = await self._pool.session(session.tenant)
        tools = [t for t in await cbm.list_tools() if t.get("name") in allowed]

        if self._llm.enabled and Capability.USE_SMART_TOOLS in session.capabilities:
            for definition in SMART_TOOL_DEFINITIONS:
                if SMART_TOOL_REQUIREMENTS[definition["name"]] <= allowed:
                    tools.append(definition)
        return tools

    async def _tools_call(self, session: Session, params: dict) -> dict:
        name = str(params.get("name") or "")
        args = dict(params.get("arguments") or {})
        project = args.get("project")

        event = AuditEvent(
            event="tools/call",
            principal=session.principal.username,
            tenant=session.tenant.name,
            tool=name,
            project=str(project) if project else None,
            extra={"role": session.role.value},
        )

        tool_label = name if name in TOOL_CAPABILITY or name in SMART_TOOL_NAMES else "unknown"

        try:
            self._authorize(session, name, args)
        except AccessDenied as exc:
            event.outcome = "denied"
            event.reason = str(exc)
            emit(event)
            TOOL_CALLS.labels(tool_label, session.tenant.name, session.role.value, "denied").inc()
            raise

        cbm = await self._pool.session(session.tenant)
        try:
            with Timer() as timer:
                if name in SMART_TOOL_NAMES:
                    event.llm_model = self._settings.litellm_model
                    text = await self._smart_tool(session, cbm, name, args, event)
                    result = {"content": [{"type": "text", "text": text}], "isError": False}
                else:
                    outcome = await cbm.call_tool(name, args)
                    result = {"content": outcome.content, "isError": outcome.is_error}
                    if outcome.is_error:
                        event.outcome = "tool_error"
        except (CbmError, LlmError) as exc:
            event.outcome = "error"
            event.reason = str(exc)
            emit(event)
            TOOL_CALLS.labels(tool_label, session.tenant.name, session.role.value, "error").inc()
            raise

        event.duration_ms = timer.ms
        emit(event)
        TOOL_DURATION.labels(tool_label).observe(timer.ms / 1000)
        TOOL_CALLS.labels(
            tool_label, session.tenant.name, session.role.value, event.outcome
        ).inc()
        return result

    async def _smart_tool(
        self, session: Session, cbm, name: str, args: dict, event: AuditEvent
    ) -> str:
        """Answer from the cache when it applies, otherwise from the model.

        A recalled answer is labelled in the audit record and in the text
        itself: a developer should be able to tell that an answer describes the
        graph as of an earlier moment, and ask again if that matters.
        """
        if self._cache is not None:
            hit = await self._cache.lookup(
                settings=self._settings,
                tenant=session.tenant,
                username=session.principal.username,
                tool=name,
                args=args,
            )
            if hit is not None:
                event.extra["cache"] = hit.kind
                event.llm_model = None
                return _label_cached(hit)

        text = await HANDLERS[name](
            session=cbm,
            llm=self._llm,
            tenant=session.tenant,
            username=session.principal.username,
            args=args,
        )
        if self._cache is not None:
            await self._cache.store(
                settings=self._settings,
                tenant=session.tenant,
                username=session.principal.username,
                tool=name,
                args=args,
                answer=text,
            )
        return text

    # ── authorization ────────────────────────────────────────────────

    def _authorize(self, session: Session, name: str, args: dict) -> None:
        allowed = session.effective_tools

        if name in SMART_TOOL_NAMES:
            if not self._llm.enabled:
                raise AccessDenied(f"{name!r} is unavailable: smart tools are disabled")
            if Capability.USE_SMART_TOOLS not in session.capabilities:
                raise AccessDenied(f"role {session.role.value!r} cannot use smart tools")
            missing = SMART_TOOL_REQUIREMENTS[name] - allowed
            if missing:
                raise AccessDenied(
                    f"{name!r} needs tools you cannot call: {', '.join(sorted(missing))}"
                )
        elif name not in allowed:
            # Deliberately does not distinguish "unknown tool" from
            # "not permitted" — the difference is itself information.
            raise AccessDenied(
                f"{name!r} is not available in this session "
                f"(role: {session.role.value}, squad: {session.tenant.name})"
            )

        if name in PROJECT_ARG_TOOLS:
            project = args.get("project")
            # When the argument is optional, let the engine raise its own error; when
            # it is supplied it is always validated.
            if project is not None and (
                not isinstance(project, str) or not session.tenant.allows_project(project)
            ):
                raise AccessDenied(
                    f"no access to project {project!r} "
                    f"(allowed: {', '.join(session.tenant.projects)})"
                )

        if name == "index_repository":
            # CBM_ALLOWED_ROOT enforces this too; checking here produces an
            # early, readable error instead of an opaque engine failure.
            repo_path = str(args.get("repo_path") or "")
            expected_root = str(self._settings.cbm_repo_root / session.tenant.name)
            if not repo_path.startswith(expected_root + "/"):
                raise AccessDenied(f"repo_path must live under {expected_root}")


def _error(message_id, code: int, message: str) -> dict:
    return {
        "jsonrpc": "2.0",
        "id": message_id,
        "error": {"code": code, "message": message},
    }


def _label_cached(hit) -> str:
    """Say plainly that an answer was recalled, and how old it is.

    An unlabelled cached answer is indistinguishable from a fresh one, which
    is exactly the confusion the epoch key exists to avoid on the storage
    side. The reader deserves the same courtesy.
    """
    age = int(hit.age_seconds)
    when = f"{age // 3600}h" if age >= 3600 else f"{max(age // 60, 1)}m"
    how = "identical question" if hit.kind == "exact" else f"similar question, {hit.similarity:.2f}"
    return f"{hit.answer}\n\n_Recalled from the answer cache ({how}, {when} old)._"
