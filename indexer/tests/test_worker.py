"""Queue behaviour tests.

The engine CLI is stubbed, so these cover the scheduling guarantees the
indexer is responsible for: serialising per project, coalescing bursts, and
surviving a failing job.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from app.repos import Binding
from app.worker import Indexer, IndexJob, JobResult


def binding(project: str = "acme-api", tenant: str = "acme") -> Binding:
    return Binding(
        full_name=f"acme/{project}",
        project=project,
        tenant=tenant,
        clone_url=f"https://example.com/acme/{project}.git",
        default_branch="main",
        workdir=Path("/tmp") / tenant / project,
        mode="fast",
        persistence=False,
    )


class RecordingIndexer(Indexer):
    """Replaces the git sync and engine call with a recorded, controllable stub."""

    def __init__(self, *args, delay: float = 0.0, fail_on: set[str] | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.calls: list[str] = []
        self.concurrent = 0
        self.max_concurrent = 0
        self._delay = delay
        self._fail_on = fail_on or set()

    async def _index(self, job: IndexJob) -> JobResult:
        self.concurrent += 1
        self.max_concurrent = max(self.max_concurrent, self.concurrent)
        try:
            self.calls.append(job.key)
            if self._delay:
                await asyncio.sleep(self._delay)
            if job.binding.project in self._fail_on:
                raise RuntimeError("stubbed failure")
            return JobResult(job, True, 0, "ok")
        finally:
            self.concurrent -= 1


def make(**kwargs) -> RecordingIndexer:
    return RecordingIndexer(
        cbm_binary="/bin/true",
        cache_root=Path("/tmp/cache"),
        repo_root=Path("/tmp/repos"),
        **kwargs,
    )


async def test_job_runs_and_records_a_result():
    indexer = make(concurrency=1)
    await indexer.start()
    try:
        assert indexer.enqueue(IndexJob(binding=binding(), trigger="manual")) is True
        await asyncio.wait_for(indexer._queue.join(), timeout=5)
        assert indexer.calls == ["acme/acme-api"]
        assert indexer.last_results["acme/acme-api"].ok is True
    finally:
        await indexer.aclose()


async def test_burst_for_one_project_is_coalesced():
    """Consecutive pushes converge on the same head; indexing each is waste."""
    indexer = make(concurrency=1, delay=0.2)
    await indexer.start()
    try:
        first = indexer.enqueue(IndexJob(binding=binding(), trigger="webhook"))
        second = indexer.enqueue(IndexJob(binding=binding(), trigger="webhook"))
        third = indexer.enqueue(IndexJob(binding=binding(), trigger="webhook"))
        assert (first, second, third) == (True, False, False)
        await asyncio.wait_for(indexer._queue.join(), timeout=10)
        assert indexer.calls == ["acme/acme-api"]
    finally:
        await indexer.aclose()


async def test_different_projects_run_concurrently():
    indexer = make(concurrency=2, delay=0.2)
    await indexer.start()
    try:
        indexer.enqueue(IndexJob(binding=binding("api"), trigger="manual"))
        indexer.enqueue(IndexJob(binding=binding("worker"), trigger="manual"))
        await asyncio.wait_for(indexer._queue.join(), timeout=10)
        assert sorted(indexer.calls) == ["acme/api", "acme/worker"]
        assert indexer.max_concurrent == 2
    finally:
        await indexer.aclose()


async def test_the_same_project_never_runs_twice_at_once():
    """The engine holds a per-project mutation lock; two runs would just block."""
    indexer = make(concurrency=4, delay=0.2)
    await indexer.start()
    try:
        indexer.enqueue(IndexJob(binding=binding("api"), trigger="manual"))
        await asyncio.sleep(0.05)
        # Accepted only because the first job already left the pending set.
        indexer.enqueue(IndexJob(binding=binding("api"), trigger="manual"))
        await asyncio.wait_for(indexer._queue.join(), timeout=10)
        assert indexer.max_concurrent == 1
    finally:
        await indexer.aclose()


async def test_a_failing_job_does_not_kill_the_worker():
    indexer = make(concurrency=1, fail_on={"broken"})
    await indexer.start()
    try:
        indexer.enqueue(IndexJob(binding=binding("broken"), trigger="manual"))
        await asyncio.wait_for(indexer._queue.join(), timeout=5)
        assert indexer.last_results["acme/broken"].ok is False

        indexer.enqueue(IndexJob(binding=binding("healthy"), trigger="manual"))
        await asyncio.wait_for(indexer._queue.join(), timeout=5)
        assert indexer.last_results["acme/healthy"].ok is True
    finally:
        await indexer.aclose()


async def test_queue_depth_returns_to_zero():
    indexer = make(concurrency=1)
    await indexer.start()
    try:
        for name in ("a", "b", "c"):
            indexer.enqueue(IndexJob(binding=binding(name), trigger="schedule"))
        await asyncio.wait_for(indexer._queue.join(), timeout=10)
        assert indexer.depth == 0
    finally:
        await indexer.aclose()


def test_job_key_combines_tenant_and_project():
    job = IndexJob(binding=binding("api", tenant="payments"))
    assert job.key == "payments/api"


@pytest.mark.parametrize("sha", ["", "a" * 40])
def test_job_accepts_a_pinned_or_floating_commit(sha):
    job = IndexJob(binding=binding(), sha=sha)
    assert job.sha == sha


async def test_administrator_settings_size_the_worker_pool():
    """The settings an administrator can edit have to actually reach the worker.

    They were defined in the store and read by nothing, which is worse than
    not offering them: the value changes, the audit records it, and the
    indexer keeps its old behaviour.
    """
    indexer = make(concurrency=1)
    indexer.apply_settings(concurrency=4, git_timeout_s=30.0, index_timeout_s=60.0)
    assert indexer._concurrency == 4
    assert indexer._git_timeout == 30.0
    assert indexer._index_timeout == 60.0

    await indexer.start()
    try:
        assert len(indexer._workers) == 4
    finally:
        await indexer.aclose()


def test_a_zero_worker_pool_is_refused():
    """Zero workers is a queue that silently never drains."""
    indexer = make(concurrency=2)
    indexer.apply_settings(concurrency=0, git_timeout_s=1.0, index_timeout_s=1.0)
    assert indexer._concurrency == 1
