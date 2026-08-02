"""Bridge to the indexing engine.

The engine speaks line-delimited JSON-RPC over stdio for its tools, and this
module keeps one engine process per tenant, serialises calls onto its single
stdio stream, and reaps processes that have gone idle.

A build of the engine with the interface included also serves a 3D graph
layout over HTTP, on loopback only. The gateway starts that on a port of its
choosing and proxies to it after authorizing the request — see ``ui_port`` and
``webui.py``.

Isolation is per process: every tenant gets its own ``CBM_CACHE_DIR``,
``CBM_ALLOWED_ROOT`` and tool profile.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import socket
import time
from dataclasses import dataclass

from .config import Settings
from .metrics import CBM_RESTARTS, CBM_SESSIONS
from .tenants import Tenant

log = logging.getLogger(__name__)

PROTOCOL_VERSION = "2025-06-18"


def _free_loopback_port() -> int:
    """A port the operating system says is free, on loopback.

    Racy in principle — something could take it between the close and the
    engine's bind. In practice the window is microseconds inside one
    container, and the alternative, a fixed range, collides for real as soon
    as two tenants start at once.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])

#: The engine can emit very large single-line responses (a full architecture dump on
#: a big monorepo). The default asyncio stream limit of 64 KiB would truncate
#: them into unparseable fragments.
_MAX_LINE_BYTES = 64 * 1024 * 1024


class CbmError(RuntimeError):
    """An engine call failed."""


@dataclass
class ToolResult:
    content: list[dict]
    is_error: bool

    def text(self) -> str:
        return "\n".join(
            part.get("text", "") for part in self.content if part.get("type") == "text"
        )


class CbmSession:
    """A single engine process. Calls are serialised over its stdio stream."""

    def __init__(self, settings: Settings, tenant: Tenant) -> None:
        self._settings = settings
        self._tenant = tenant
        self._proc: asyncio.subprocess.Process | None = None
        self._lock = asyncio.Lock()
        self._next_id = 0
        self._stderr_task: asyncio.Task | None = None
        self._started_before = False
        self._ui_port: int | None = None
        self.last_used = time.monotonic()

    @property
    def ui_port(self) -> int | None:
        """The loopback port this tenant's engine serves its layout on."""
        return self._ui_port

    async def ensure_started(self) -> None:
        """Start the engine if it is not running. Idempotent.

        A tool call does this on its way past; the graph page needs it done
        without making a call, because the layout it wants is served by the
        process rather than answered over the stdio pipe.
        """
        async with self._lock:
            await self._ensure_started()

    # ── lifecycle ────────────────────────────────────────────────────

    @property
    def cache_dir(self) -> str:
        return str(self._settings.cbm_cache_root / "tenant" / self._tenant.name)

    @property
    def repo_root(self) -> str:
        return str(self._settings.cbm_repo_root / self._tenant.name)

    def _env(self) -> dict[str, str]:
        env = dict(os.environ)
        env.update(
            {
                "CBM_CACHE_DIR": self.cache_dir,
                # Confines index_repository to the tenant's repository root.
                # The gateway ACL is the primary control; this is the backstop.
                "CBM_ALLOWED_ROOT": self.repo_root,
                "CBM_LOG_LEVEL": os.getenv("CBM_LOG_LEVEL", "warn"),
                "CBM_LOG_FORMAT": "json",
            }
        )
        return env

    async def _ensure_started(self) -> asyncio.subprocess.Process:
        proc = self._proc
        if proc is not None and proc.returncode is None:
            return proc

        try:
            os.makedirs(self.cache_dir, exist_ok=True)
        except OSError as exc:
            raise CbmError(f"cannot create cache directory {self.cache_dir}: {exc}") from exc

        argv = [self._settings.cbm_binary, *self._tenant.cbm_profile_flag()]

        # The engine can also serve the 3D layout its own interface uses, over
        # HTTP. That layout is 860 lines of C reading the graph database
        # directly; reimplementing it here would be slower and would drift.
        #
        # The server binds 127.0.0.1 only and has no authentication of its
        # own — which is why the port is chosen by us, kept in this process,
        # and never published. The gateway authorizes a request and then
        # proxies it, so the trust boundary is the same one the stdio pipe
        # already has: the engine process is trusted, and reaching it is not.
        if self._settings.engine_ui_enabled:
            self._ui_port = _free_loopback_port()
            argv += [f"--port={self._ui_port}", "--ui=true"]

        reason = "restart" if self._started_before else "first_start"
        log.info("starting engine for tenant=%s argv=%s", self._tenant.name, argv)
        try:
            proc = await asyncio.create_subprocess_exec(
                *argv,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=self._env(),
                limit=_MAX_LINE_BYTES,
            )
        except FileNotFoundError as exc:
            # A missing or unreadable engine binary is a deployment problem.
            # Surfacing it as a JSON-RPC error names the cause; letting it
            # escape produces an opaque HTTP 500.
            raise CbmError(
                f"engine binary not found: {self._settings.cbm_binary} "
                f"(set CBM_BINARY, or install codebase-memory-mcp)"
            ) from exc
        except OSError as exc:
            raise CbmError(f"cannot start the engine ({self._settings.cbm_binary}): {exc}") from exc
        self._proc = proc
        self._next_id = 0
        self._started_before = True
        self._stderr_task = asyncio.create_task(self._drain_stderr(proc))
        CBM_RESTARTS.labels(self._tenant.name, reason).inc()
        CBM_SESSIONS.inc()
        await self._handshake()
        return proc

    async def _drain_stderr(self, proc: asyncio.subprocess.Process) -> None:
        """An unread stderr pipe fills up and blocks the child process."""
        assert proc.stderr is not None
        try:
            while line := await proc.stderr.readline():
                log.debug(
                    "cbm[%s] %s",
                    self._tenant.name,
                    line.decode(errors="replace").rstrip(),
                )
        except (asyncio.CancelledError, ValueError):
            pass

    async def _handshake(self) -> None:
        await self._request(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "repo-mcp-gateway", "version": "0.1.0"},
            },
        )
        await self._notify("notifications/initialized", {})

    async def close(self) -> None:
        proc, self._proc = self._proc, None
        if self._stderr_task is not None:
            self._stderr_task.cancel()
            self._stderr_task = None
        if proc is None or proc.returncode is not None:
            return
        CBM_SESSIONS.dec()
        try:
            proc.terminate()
            await asyncio.wait_for(proc.wait(), timeout=10)
        except (TimeoutError, ProcessLookupError):
            with contextlib.suppress(ProcessLookupError):
                proc.kill()

    # ── JSON-RPC ─────────────────────────────────────────────────────

    async def _write(self, payload: dict) -> None:
        proc = self._proc
        assert proc is not None and proc.stdin is not None
        proc.stdin.write(json.dumps(payload, separators=(",", ":")).encode() + b"\n")
        await proc.stdin.drain()

    async def _notify(self, method: str, params: dict) -> None:
        await self._write({"jsonrpc": "2.0", "method": method, "params": params})

    async def _request(self, method: str, params: dict) -> dict:
        proc = self._proc
        assert proc is not None and proc.stdout is not None
        self._next_id += 1
        request_id = self._next_id
        await self._write(
            {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}
        )

        timeout = self._settings.cbm_call_timeout_s
        while True:
            try:
                line = await asyncio.wait_for(proc.stdout.readline(), timeout=timeout)
            except TimeoutError as exc:
                # A timeout leaves the stream in an unknown state: the late
                # reply would be mistaken for the next call's result. Tearing
                # the process down is the only safe exit.
                await self.close()
                raise CbmError(f"engine call timed out after {timeout}s: {method}") from exc
            if not line:
                await self.close()
                raise CbmError("engine process exited unexpectedly")
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                log.warning("cbm[%s] unparseable line: %r", self._tenant.name, line[:200])
                continue
            if message.get("id") != request_id:
                continue  # server-side notification or a stray log line
            if "error" in message:
                err = message["error"]
                raise CbmError(
                    f"{err.get('message', 'unknown error')} (code {err.get('code')})"
                )
            return message.get("result") or {}

    # ── public API ───────────────────────────────────────────────────

    async def call_tool(self, name: str, arguments: dict) -> ToolResult:
        async with self._lock:
            await self._ensure_started()
            self.last_used = time.monotonic()
            result = await self._request("tools/call", {"name": name, "arguments": arguments})
        return ToolResult(
            content=result.get("content") or [],
            is_error=bool(result.get("isError")),
        )

    async def list_tools(self) -> list[dict]:
        async with self._lock:
            await self._ensure_started()
            self.last_used = time.monotonic()
            result = await self._request("tools/list", {})
        return result.get("tools") or []


class CbmPool:
    """One session per tenant, with idle reaping."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._sessions: dict[str, CbmSession] = {}
        self._guard = asyncio.Lock()
        self._reaper: asyncio.Task | None = None

    async def start(self) -> None:
        self._reaper = asyncio.create_task(self._reap_loop())

    async def aclose(self) -> None:
        if self._reaper is not None:
            self._reaper.cancel()
            self._reaper = None
        async with self._guard:
            sessions = list(self._sessions.values())
            self._sessions.clear()
        await asyncio.gather(*(s.close() for s in sessions), return_exceptions=True)

    async def session(self, tenant: Tenant) -> CbmSession:
        async with self._guard:
            session = self._sessions.get(tenant.name)
            if session is None:
                session = CbmSession(self._settings, tenant)
                self._sessions[tenant.name] = session
            return session

    async def _reap_loop(self) -> None:
        interval = max(30.0, self._settings.cbm_idle_timeout_s / 4)
        try:
            while True:
                await asyncio.sleep(interval)
                cutoff = time.monotonic() - self._settings.cbm_idle_timeout_s
                async with self._guard:
                    stale = [n for n, s in self._sessions.items() if s.last_used < cutoff]
                    victims = [self._sessions.pop(n) for n in stale]
                for name, session in zip(stale, victims, strict=True):
                    log.info("reaping idle engine session for tenant=%s", name)
                    await session.close()
        except asyncio.CancelledError:
            pass
