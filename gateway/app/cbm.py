"""Bridge to the codebase-memory-mcp (CBM) engine.

CBM speaks line-delimited JSON-RPC over stdio and nothing else — there is no
network transport (see docs/cbm-constraints.md). This module keeps one CBM
process per tenant, serialises calls onto its single stdio stream, and reaps
processes that have gone idle.

Isolation is per process: every tenant gets its own ``CBM_CACHE_DIR``,
``CBM_ALLOWED_ROOT`` and tool profile.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import time
from dataclasses import dataclass

from .config import Settings
from .tenants import Tenant

log = logging.getLogger(__name__)

PROTOCOL_VERSION = "2025-06-18"

#: CBM can emit very large single-line responses (a full architecture dump on
#: a big monorepo). The default asyncio stream limit of 64 KiB would truncate
#: them into unparseable fragments.
_MAX_LINE_BYTES = 64 * 1024 * 1024


class CbmError(RuntimeError):
    """A CBM call failed."""


@dataclass
class ToolResult:
    content: list[dict]
    is_error: bool

    def text(self) -> str:
        return "\n".join(
            part.get("text", "") for part in self.content if part.get("type") == "text"
        )


class CbmSession:
    """A single CBM process. Calls are serialised over its stdio stream."""

    def __init__(self, settings: Settings, tenant: Tenant) -> None:
        self._settings = settings
        self._tenant = tenant
        self._proc: asyncio.subprocess.Process | None = None
        self._lock = asyncio.Lock()
        self._next_id = 0
        self._stderr_task: asyncio.Task | None = None
        self.last_used = time.monotonic()

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

        os.makedirs(self.cache_dir, exist_ok=True)
        argv = [self._settings.cbm_binary, *self._tenant.cbm_profile_flag()]
        log.info("starting CBM for tenant=%s argv=%s", self._tenant.name, argv)
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=self._env(),
            limit=_MAX_LINE_BYTES,
        )
        self._proc = proc
        self._next_id = 0
        self._stderr_task = asyncio.create_task(self._drain_stderr(proc))
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
                raise CbmError(f"CBM call timed out after {timeout}s: {method}") from exc
            if not line:
                await self.close()
                raise CbmError("CBM process exited unexpectedly")
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
                    log.info("reaping idle CBM session for tenant=%s", name)
                    await session.close()
        except asyncio.CancelledError:
            pass
