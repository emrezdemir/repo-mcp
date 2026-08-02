"""Indexer service: discovery, webhooks, scheduled rescans and CI triggers."""

from __future__ import annotations

import asyncio
import hmac
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse

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
    """

    def __init__(self, config: ScanConfig) -> None:
        self._config = config
        self._bindings: dict[str, Binding] = {}
        self._lock = asyncio.Lock()

    @property
    def bindings(self) -> dict[str, Binding]:
        return dict(self._bindings)

    async def refresh(self) -> int:
        async with self._lock:
            discovered: dict[str, Binding] = {}
            for connector in self._config.connectors:
                try:
                    provider = connector.build()
                except ValueError as exc:
                    log.error("connector %s is misconfigured: %s", connector.name, exc)
                    continue
                count = 0
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


def create_app() -> FastAPI:
    repo_root = Path(os.getenv("CBM_REPO_ROOT", "/var/lib/repo-mcp/repos"))
    cache_root = Path(os.getenv("CBM_CACHE_ROOT", "/var/lib/repo-mcp/cache"))
    config = ScanConfig.load(
        Path(os.getenv("SCAN_CONFIG", "/etc/repo-mcp/scan.yaml")), repo_root
    )
    cache = BindingCache(config)
    indexer = Indexer(
        cbm_binary=os.getenv("CBM_BINARY", "codebase-memory-mcp"),
        cache_root=cache_root,
        repo_root=repo_root,
        concurrency=int(os.getenv("INDEX_CONCURRENCY", "2")),
    )
    rescan_interval = float(os.getenv("RESCAN_INTERVAL_S", "86400"))
    ci_token = os.getenv("CI_TRIGGER_TOKEN", "")

    async def rescan_loop() -> None:
        while True:
            try:
                total = await cache.refresh()
                log.info("scheduled rescan: %d repositories, queueing full pass", total)
                for binding in cache.bindings.values():
                    indexer.enqueue(IndexJob(binding=binding, trigger="schedule"))
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - the loop must survive
                log.exception("scheduled rescan failed")
            await asyncio.sleep(rescan_interval)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        await indexer.start()
        task = asyncio.create_task(rescan_loop())
        try:
            yield
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            await indexer.aclose()

    app = FastAPI(title="repo-mcp indexer", lifespan=lifespan)

    @app.get("/healthz")
    async def healthz() -> dict:
        return {"status": "ok", "queue_depth": indexer.depth}

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
            return JSONResponse({"error": str(exc)}, status_code=400)

        if is_deletion(event):
            return JSONResponse({"queued": False, "reason": "branch deletion"})

        binding = await cache.lookup(event.full_name)
        if binding is None:
            return JSONResponse(
                {"queued": False, "reason": f"{event.full_name} is not in scope"}
            )

        # Only the default branch feeds the shared graph. Feature branches are
        # handled on demand by the gateway, not by the central index.
        if event.ref and not event.ref.endswith(f"/{binding.default_branch}"):
            return JSONResponse({"queued": False, "reason": "not the default branch"})

        queued = indexer.enqueue(
            IndexJob(binding=binding, sha=event.sha, trigger=f"webhook:{provider}")
        )
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
