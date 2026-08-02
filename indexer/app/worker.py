"""Indexing worker.

The engine ships a git-polling watcher, but a central deployment turns that into N
repositories being polled forever. Webhook- and schedule-driven indexing is
deterministic, has measurable latency, and costs nothing while idle.

The engine holds an OS-backed mutation lock per project, so two workers indexing the
same project would simply block each other. The queue therefore serialises per
project and coalesces bursts.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path

from .metrics import COALESCED, JOB_DURATION, JOBS, QUEUE_DEPTH
from .repos import Binding

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class IndexJob:
    binding: Binding
    #: Commit to index. Empty means "whatever the default branch points at".
    sha: str = ""
    trigger: str = "manual"

    @property
    def key(self) -> str:
        return f"{self.binding.tenant}/{self.binding.project}"


@dataclass
class JobResult:
    job: IndexJob
    ok: bool
    duration_s: int
    detail: str = ""


class Indexer:
    def __init__(
        self,
        *,
        cbm_binary: str,
        cache_root: Path,
        repo_root: Path,
        git_timeout_s: float = 600.0,
        index_timeout_s: float = 3600.0,
        concurrency: int = 2,
    ) -> None:
        self._cbm = cbm_binary
        self._cache_root = cache_root
        self._repo_root = repo_root
        self._git_timeout = git_timeout_s
        self._index_timeout = index_timeout_s
        self._concurrency = concurrency
        self._queue: asyncio.Queue[IndexJob] = asyncio.Queue()
        self._project_locks: dict[str, asyncio.Lock] = {}
        self._pending: set[str] = set()
        self._workers: list[asyncio.Task] = []
        self.last_results: dict[str, JobResult] = {}

    # ── lifecycle ────────────────────────────────────────────────────

    async def start(self) -> None:
        self._workers = [
            asyncio.create_task(self._run(), name=f"indexer-{i}")
            for i in range(self._concurrency)
        ]

    async def aclose(self) -> None:
        for task in self._workers:
            task.cancel()
        await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers.clear()

    @property
    def depth(self) -> int:
        return self._queue.qsize()

    def enqueue(self, job: IndexJob) -> bool:
        """Queue a job, coalescing with one already waiting for that project.

        Consecutive pushes converge on the same head; indexing each one
        separately is wasted work.
        """
        if job.key in self._pending:
            log.info("coalescing job for %s (trigger=%s)", job.key, job.trigger)
            COALESCED.labels(job.trigger).inc()
            return False
        self._pending.add(job.key)
        self._queue.put_nowait(job)
        QUEUE_DEPTH.set(self._queue.qsize())
        return True

    # ── execution ────────────────────────────────────────────────────

    async def _run(self) -> None:
        while True:
            job = await self._queue.get()
            lock = self._project_locks.setdefault(job.key, asyncio.Lock())
            try:
                async with lock:
                    # Released before the work starts so a push arriving mid-index
                    # still schedules a follow-up run.
                    self._pending.discard(job.key)
                    result = await self._index(job)
                    self.last_results[job.key] = result
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - a worker must not die
                log.exception("indexing failed for %s", job.key)
                self.last_results[job.key] = JobResult(job, False, 0, str(exc))
                JOBS.labels(job.trigger, "error").inc()
            finally:
                self._pending.discard(job.key)
                self._queue.task_done()
                QUEUE_DEPTH.set(self._queue.qsize())

    async def _index(self, job: IndexJob) -> JobResult:
        binding = job.binding
        started = time.monotonic()
        log.info(
            "indexing %s sha=%s mode=%s trigger=%s",
            job.key, job.sha[:8] or "HEAD", binding.mode, job.trigger,
        )

        await self._sync_worktree(job)

        args = {
            "repo_path": str(binding.workdir),
            "mode": binding.mode,
            "name": binding.project,
            "persistence": binding.persistence,
        }
        code, out, err = await self._cbm_cli(binding.tenant, args)
        elapsed = time.monotonic() - started
        JOB_DURATION.labels(binding.mode).observe(elapsed)

        if code != 0:
            outcome = "timeout" if code == 124 else "failed"
            JOBS.labels(job.trigger, outcome).inc()
            log.error(
                "indexing %s failed rc=%s after %ds: %s",
                job.key, code, int(elapsed), err[-2000:],
            )
            return JobResult(job, False, int(elapsed), err[-2000:])

        JOBS.labels(job.trigger, "ok").inc()
        log.info("indexed %s in %ds", job.key, int(elapsed))
        return JobResult(job, True, int(elapsed), out[-2000:])

    async def _sync_worktree(self, job: IndexJob) -> None:
        binding = job.binding
        if not (binding.workdir / ".git").is_dir():
            binding.workdir.parent.mkdir(parents=True, exist_ok=True)
            await self._git(
                binding.workdir.parent,
                "clone", "--filter=blob:none", binding.clone_url, binding.workdir.name,
            )

        await self._git(binding.workdir, "fetch", "--prune", "origin")
        if job.sha:
            # Pin to the commit the webhook reported: the branch tip may have
            # moved on, but the indexed tree is then a known point.
            await self._git(binding.workdir, "checkout", "--force", job.sha)
        else:
            await self._git(
                binding.workdir, "checkout", "--force", f"origin/{binding.default_branch}"
            )

    async def _git(self, cwd: Path, *args: str) -> None:
        proc = await asyncio.create_subprocess_exec(
            "git", *args,
            cwd=str(cwd),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            _, err = await asyncio.wait_for(proc.communicate(), timeout=self._git_timeout)
        except TimeoutError:
            proc.kill()
            await proc.wait()
            raise RuntimeError(f"git {' '.join(args)} timed out") from None
        if proc.returncode != 0:
            raise RuntimeError(
                f"git {' '.join(args)} failed (rc={proc.returncode}): "
                f"{err.decode(errors='replace')[-500:]}"
            )

    async def _cbm_cli(self, tenant: str, args: dict) -> tuple[int, str, str]:
        env = dict(os.environ)
        cache_dir = self._cache_root / "tenant" / tenant
        cache_dir.mkdir(parents=True, exist_ok=True)
        env.update(
            {
                "CBM_CACHE_DIR": str(cache_dir),
                "CBM_ALLOWED_ROOT": str(self._repo_root / tenant),
                "CBM_LOG_FORMAT": "json",
            }
        )

        proc = await asyncio.create_subprocess_exec(
            self._cbm, "cli", "--json", "index_repository",
            json.dumps(args, separators=(",", ":")),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        try:
            out, err = await asyncio.wait_for(proc.communicate(), timeout=self._index_timeout)
        except TimeoutError:
            proc.kill()
            await proc.wait()
            return 124, "", "index_repository timed out"
        return (
            proc.returncode or 0,
            out.decode(errors="replace"),
            err.decode(errors="replace"),
        )
