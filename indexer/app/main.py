"""Indexer service: discovery, webhooks, scheduled rescans and CI triggers."""

from __future__ import annotations

import asyncio
import hmac
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse, Response
from repo_mcp_common.bootstrap import inspect_state
from repo_mcp_common.db import Database, DatabaseUnavailable
from repo_mcp_common.store import ConfigStore

from .metrics import DISCOVERED_REPOS, DISCOVERY_RUNS, WEBHOOKS, render
from .repos import Binding, ScanConfig
from .webhooks import (
    PushEvent,
    WebhookError,
    is_deletion,
    parse_bitbucket,
    parse_github,
    parse_gitlab,
    verify_bitbucket,
    verify_github,
    verify_gitlab,
)
from .worker import Indexer, IndexJob

log = logging.getLogger(__name__)


class BindingCache:
    """Discovered repositories, refreshed by the periodic rescan.

    Webhooks arrive for repositories the platform may not have discovered yet
    (someone created one an hour ago). A miss triggers a rediscovery rather
    than dropping the event.

    The connector list comes from the configuration database and is re-read on
    every refresh, so a connector an administrator adds is picked up by the
    next rescan without a restart.
    """

    def __init__(self, config: ScanConfig, store: ConfigStore | None = None,
                 repo_root: Path | None = None) -> None:
        self._config = config
        self._store = store
        self._repo_root = repo_root
        self._bindings: dict[str, Binding] = {}
        self._lock = asyncio.Lock()

    async def _reload_config(self) -> None:
        if self._store is None or self._repo_root is None:
            return
        snapshot = await self._store.snapshot()
        self._config = ScanConfig.from_dict(
            snapshot.scan_document, self._repo_root, snapshot.secrets
        )

    @property
    def bindings(self) -> dict[str, Binding]:
        return dict(self._bindings)

    async def refresh(self) -> int:
        await self._reload_config()
        async with self._lock:
            discovered: dict[str, Binding] = {}
            for connector in self._config.connectors:
                try:
                    provider = connector.build()
                except ValueError as exc:
                    log.error("connector %s is misconfigured: %s", connector.name, exc)
                    DISCOVERY_RUNS.labels(connector.name, "misconfigured").inc()
                    continue
                count = 0
                outcome = "ok"
                try:
                    async for repo in provider.discover():
                        if not connector.matches(repo):
                            continue
                        binding = self._config.bind(connector, repo)
                        discovered[binding.full_name] = binding
                        count += 1
                except Exception:  # noqa: BLE001 - one bad connector must not
                    # invalidate the others; keep whatever it already yielded.
                    log.exception("discovery failed for connector %s", connector.name)
                    outcome = "error"
                DISCOVERY_RUNS.labels(connector.name, outcome).inc()
                DISCOVERED_REPOS.labels(connector.name, connector.tenant).set(count)
                log.info("connector %s matched %d repositories", connector.name, count)
            self._bindings = discovered
            return len(discovered)

    async def lookup(self, full_name: str) -> Binding | None:
        binding = self._bindings.get(full_name)
        if binding is not None:
            return binding
        log.info("unknown repository %s; refreshing discovery", full_name)
        await self.refresh()
        return self._bindings.get(full_name)


def create_app(database: Database | None = None) -> FastAPI:
    repo_root = Path(os.getenv("CBM_REPO_ROOT", "/var/lib/repo-mcp/repos"))
    cache_root = Path(os.getenv("CBM_CACHE_ROOT", "/var/lib/repo-mcp/cache"))
    database = database or Database()
    store = ConfigStore(database)

    # Start with an empty connector list; the first refresh loads it from the
    # database. A file is no longer read at runtime.
    cache = BindingCache(ScanConfig((), repo_root), store, repo_root)
    indexer = Indexer(
        cbm_binary=os.getenv("CBM_BINARY", "codebase-memory-mcp"),
        cache_root=cache_root,
        repo_root=repo_root,
    )
    ci_token = os.getenv("CI_TRIGGER_TOKEN", "")
    state = {"ready": False, "reason": "starting"}

    async def rescan_interval() -> float:
        """Read the interval afresh each pass, so a change lands without a restart."""
        try:
            snapshot = await store.snapshot()
            return float(snapshot.setting("indexer.rescan_interval_seconds"))
        except Exception:  # noqa: BLE001 - a database blip must not stop the loop
            return 86400.0

    async def rescan_loop() -> None:
        while True:
            interval = await rescan_interval()
            try:
                if not state["ready"]:
                    await asyncio.sleep(min(interval, 30))
                    continue
                total = await cache.refresh()
                log.info("scheduled rescan: %d repositories, queueing full pass", total)
                for binding in cache.bindings.values():
                    indexer.enqueue(IndexJob(binding=binding, trigger="schedule"))
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - the loop must survive
                log.exception("scheduled rescan failed")
            await asyncio.sleep(interval)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        try:
            await database.wait_until_ready()
            bootstrap_state = await inspect_state(database)
            state["ready"] = bootstrap_state.ready
            state["reason"] = bootstrap_state.explain()
            if not bootstrap_state.ready:
                log.error("not ready: %s", bootstrap_state.explain())
            else:
                snapshot = await store.snapshot()
                indexer.apply_settings(
                    concurrency=int(snapshot.setting("indexer.concurrency")),
                    git_timeout_s=float(snapshot.setting("indexer.git_timeout_seconds")),
                    index_timeout_s=float(snapshot.setting("indexer.index_timeout_seconds")),
                )
        except DatabaseUnavailable as exc:
            state["ready"] = False
            state["reason"] = str(exc)
            log.error("%s", exc)

        await indexer.start()
        task = asyncio.create_task(rescan_loop())
        try:
            yield
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            await indexer.aclose()
            await database.aclose()

    app = FastAPI(title="repo-mcp indexer", lifespan=lifespan)

    @app.get("/healthz")
    async def healthz() -> dict:
        return {"status": "ok", "queue_depth": indexer.depth}

    @app.get("/readyz")
    async def readyz() -> JSONResponse:
        if not state["ready"]:
            return JSONResponse(
                {"status": "not_ready", "reason": state["reason"]}, status_code=503
            )
        return JSONResponse(
            {
                "status": "ok",
                "queue_depth": indexer.depth,
                "repos": len(cache.bindings),
                "database": database.env.redacted_url(),
            }
        )

    @app.get("/metrics")
    async def metrics() -> Response:
        payload, content_type = render()
        return Response(content=payload, media_type=content_type)

    @app.get("/repos")
    async def repos() -> dict:
        return {
            "count": len(cache.bindings),
            "repos": sorted(
                {"full_name": b.full_name, "project": b.project, "tenant": b.tenant}
                for b in cache.bindings.values()
            ),
        }

    @app.post("/rescan")
    async def rescan(authorization: str | None = Header(default=None)) -> JSONResponse:
        if not _ci_authorized(authorization, ci_token):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        total = await cache.refresh()
        queued = sum(
            indexer.enqueue(IndexJob(binding=b, trigger="manual"))
            for b in cache.bindings.values()
        )
        return JSONResponse({"discovered": total, "queued": queued})

    @app.post("/trigger")
    async def trigger(
        request: Request, authorization: str | None = Header(default=None)
    ) -> JSONResponse:
        """CI hook: index one repository at a specific commit."""
        if not _ci_authorized(authorization, ci_token):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        body = await request.json()
        full_name = str(body.get("repository") or "")
        binding = await cache.lookup(full_name)
        if binding is None:
            return JSONResponse({"error": f"unknown repository: {full_name}"}, status_code=404)
        queued = indexer.enqueue(
            IndexJob(binding=binding, sha=str(body.get("sha") or ""), trigger="ci")
        )
        return JSONResponse({"queued": queued, "project": binding.project})

    @app.post("/webhook/{provider}")
    async def webhook(
        provider: str,
        request: Request,
        x_hub_signature_256: str | None = Header(default=None),
        x_hub_signature: str | None = Header(default=None),
        x_gitlab_token: str | None = Header(default=None),
    ) -> JSONResponse:
        body = await request.body()
        secret = os.getenv(f"WEBHOOK_SECRET_{provider.upper()}", "")
        if not secret:
            return JSONResponse(
                {"error": f"no webhook secret configured for {provider}"}, status_code=503
            )

        try:
            event = _verify_and_parse(
                provider, body, secret,
                github_sig=x_hub_signature_256,
                bitbucket_sig=x_hub_signature,
                gitlab_token=x_gitlab_token,
                payload=await request.json(),
            )
        except WebhookError as exc:
            log.warning("rejected %s webhook: %s", provider, exc)
            WEBHOOKS.labels(provider, "rejected").inc()
            return JSONResponse({"error": str(exc)}, status_code=400)

        if is_deletion(event):
            WEBHOOKS.labels(provider, "ignored_deletion").inc()
            return JSONResponse({"queued": False, "reason": "branch deletion"})

        binding = await cache.lookup(event.full_name)
        if binding is None:
            WEBHOOKS.labels(provider, "out_of_scope").inc()
            return JSONResponse(
                {"queued": False, "reason": f"{event.full_name} is not in scope"}
            )

        # Only the default branch feeds the shared graph. Feature branches are
        # handled on demand by the gateway, not by the central index.
        if event.ref and not event.ref.endswith(f"/{binding.default_branch}"):
            WEBHOOKS.labels(provider, "ignored_branch").inc()
            return JSONResponse({"queued": False, "reason": "not the default branch"})

        queued = indexer.enqueue(
            IndexJob(binding=binding, sha=event.sha, trigger=f"webhook:{provider}")
        )
        WEBHOOKS.labels(provider, "queued" if queued else "coalesced").inc()
        return JSONResponse({"queued": queued, "project": binding.project})

    return app


def _verify_and_parse(
    provider: str,
    body: bytes,
    secret: str,
    *,
    github_sig: str | None,
    bitbucket_sig: str | None,
    gitlab_token: str | None,
    payload: dict,
) -> PushEvent:
    if provider == "github":
        verify_github(body, github_sig, secret)
        return parse_github(payload)
    if provider == "gitlab":
        verify_gitlab(gitlab_token, secret)
        return parse_gitlab(payload)
    if provider == "bitbucket":
        verify_bitbucket(body, bitbucket_sig, secret)
        return parse_bitbucket(payload)
    raise WebhookError(f"unsupported provider: {provider}")


def _ci_authorized(authorization: str | None, expected: str) -> bool:
    if not expected or not authorization:
        return False
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer":
        return False
    return hmac.compare_digest(token.strip(), expected)
