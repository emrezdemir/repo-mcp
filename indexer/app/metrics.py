"""Prometheus metrics for the indexer.

Queue depth and job duration are the two numbers that decide how many indexer
replicas an organisation needs, so they are exported before anything else.
"""

from __future__ import annotations

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest

QUEUE_DEPTH = Gauge(
    "repo_mcp_index_queue_depth",
    "Jobs waiting to be indexed.",
)

JOBS = Counter(
    "repo_mcp_index_jobs_total",
    "Indexing jobs, by what triggered them and how they ended.",
    ["trigger", "outcome"],
)

JOB_DURATION = Histogram(
    "repo_mcp_index_duration_seconds",
    "Wall-clock duration of an indexing job, including the git sync.",
    ["mode"],
    # A small repository indexes in seconds; a large monorepo can take an hour.
    buckets=(1, 5, 15, 30, 60, 180, 300, 600, 1800, 3600),
)

COALESCED = Counter(
    "repo_mcp_index_coalesced_total",
    "Jobs dropped because one was already queued for the same project.",
    ["trigger"],
)

DISCOVERED_REPOS = Gauge(
    "repo_mcp_discovered_repos",
    "Repositories currently in scope, by connector.",
    ["connector", "tenant"],
)

DISCOVERY_RUNS = Counter(
    "repo_mcp_discovery_runs_total",
    "Discovery passes, by connector and outcome.",
    ["connector", "outcome"],
)

WEBHOOKS = Counter(
    "repo_mcp_webhooks_total",
    "Webhooks received, by provider and outcome.",
    ["provider", "outcome"],
)


def render() -> tuple[bytes, str]:
    """Return the exposition payload and its content type."""
    return generate_latest(), CONTENT_TYPE_LATEST
