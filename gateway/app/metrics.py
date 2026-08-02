"""Prometheus metrics.

These exist to make scaling decisions on evidence rather than intuition:
queue depth and tool latency are what an autoscaler reads, and the denial
counter is what tells you an authorization change had an effect.

Label cardinality is kept deliberately low — tool, tenant and outcome are
bounded sets. Project names are not labels; they belong in the audit log.
"""

from __future__ import annotations

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest

REQUESTS = Counter(
    "repo_mcp_requests_total",
    "MCP requests received, by JSON-RPC method and outcome.",
    ["method", "outcome"],
)

TOOL_CALLS = Counter(
    "repo_mcp_tool_calls_total",
    "Tool calls, by tool, tenant, role and outcome.",
    ["tool", "tenant", "role", "outcome"],
)

TOOL_DURATION = Histogram(
    "repo_mcp_tool_duration_seconds",
    "Wall-clock duration of a tool call.",
    ["tool"],
    # Graph queries answer in milliseconds; an LLM-backed tool takes seconds.
    # The buckets have to span both without hiding either.
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60, 120),
)

AUTH_FAILURES = Counter(
    "repo_mcp_auth_failures_total",
    "Rejected requests, by stage.",
    ["stage"],
)

CBM_SESSIONS = Gauge(
    "repo_mcp_cbm_sessions",
    "Live engine processes, one per active tenant.",
)

CBM_RESTARTS = Counter(
    "repo_mcp_cbm_restarts_total",
    "Engine processes started, including restarts after a timeout or crash.",
    ["tenant", "reason"],
)

LLM_CALLS = Counter(
    "repo_mcp_llm_calls_total",
    "Requests to the LiteLLM proxy, by model and outcome.",
    ["model", "outcome"],
)

LLM_DURATION = Histogram(
    "repo_mcp_llm_duration_seconds",
    "Wall-clock duration of a LiteLLM request.",
    ["model"],
    buckets=(0.5, 1, 2.5, 5, 10, 20, 40, 80, 160),
)


def render() -> tuple[bytes, str]:
    """Return the exposition payload and its content type."""
    return generate_latest(), CONTENT_TYPE_LATEST
